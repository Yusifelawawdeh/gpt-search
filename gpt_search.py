#!/bin/env python3

from bs4 import BeautifulSoup
from duckduckgo_search import ddg
from joblib import Memory
from pprint import pprint
import argparse
import datetime
import json
import openai
import os
import requests
import sys
import tiktoken

cachedir = os.path.join(os.path.dirname(__file__), ".cache")
memory = Memory(cachedir, verbose=0)

max_token_count = {
    "gpt-4": 8192,
    "gpt-3.5-turbo": 4097
}

# Set up the OpenAI API client
openai.api_key = os.environ.get("OPENAI_API_KEY")

gpt_query_count = 0
@memory.cache
def gpt(prompt, model=None):
    assert len(prompt) > 25

    global gpt_query_count
    gpt_query_count += 1

    response = openai.ChatCompletion.create(
        model=model or args.model,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0]['message']['content']

def token_count(text):
    encoding = tiktoken.encoding_for_model(args.model)
    # tiktoken seems to be undercounting tokens compared to the API
    return len(encoding.encode(text)) * 2

def background_text(background):
    return "\n\n".join(
        f"{subject}:\n{contents}" for subject, contents in background.items()
    )

def shorten(background):
    for subject in background:
        if not background[subject]:
            continue
        while token_count(background[subject]) > max_token_count[args.model]:
            background[subject] = background[subject][:int(len(background[subject]) * .9)]
    return background

def summarize(background):
    for subject in background:
        if not background[subject]:
            continue
        if token_count(background_text(background)) <= max_token_count[args.model]:
            return background
        background[subject] = gpt(
            f"Concisely summarize the facts about {subject}:\n" + background[subject])

    return background

@memory.cache
def ddg_top_hit(topic):
    if args.verbose:
        print("Search DDG for:", topic)
    results = ddg(topic)
    for result in results:
        if args.verbose:
            print("  Fetching", result['href'])
        (title, content) = fetch_url_and_extract_info(result['href'])
        if content:
            return (result['href'], title, content)

@memory.cache
def fetch_url_and_extract_info(url):
    try:
        # Fetch the URL
        response = requests.get(url)

        # Check if the request was successful
        if response.status_code == 200:
            # Parse the HTML content using BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')

            # Extract the text from the HTML
            text = ' '.join(soup.stripped_strings)
            title = soup.title.string

            return (title, text)
        else:
            print(f"Error fetching {url}: {response.status_code}")
            return (None, None)
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return (None, None)

args = None
def main():
    parser = argparse.ArgumentParser(
        description="""Combine GPT with DuckDuckGo to answer questions.
        
        Beware that this will perform up to 5 GPT queries.""")
    parser.add_argument("--4", "-4", help="Use GPT4 (slower, costs more money)",
                        dest='gpt4', action="store_true")
    parser.add_argument("--verbose", "-v", help="Verbose output", action="store_true")
    parser.add_argument("question", help="What do you want to ask?")
    global args
    args = parser.parse_args()

    if args.gpt4:
        args.model = "gpt-4"
    else:
        args.model = "gpt-3.5-turbo"

    today_prompt = f"Today is {datetime.date.today().strftime('%A, %B %d, %Y')}."
    search_prompt = (f"{today_prompt}\n\n"
                     f"I want to know: {args.question}\n\n"
                     "What 3 search topics would help you answer this "
                     "question? Answer in a JSON list only.")
    search_text = gpt(search_prompt)
    searches = json.loads(search_text)
    background = {}
    sources = []
    for search in searches:
        source, title, content = ddg_top_hit(search)
        background[search] = content
        sources.append((source, title))

    if args.verbose:
        pprint(("fetched:", {search : len(content) for search, content in background.items()}))
    background = shorten(background)
    if args.verbose:
        pprint(("shortened:", {search : len(content) for search, content in background.items()}))
    background = summarize(background)
    if args.verbose:
        pprint(("summarized:", {search : len(content) for search, content in background.items()}))
    print(
        gpt(f"{background_text(background)}\n\n{today_prompt}\n\n{args.question}")
    )
    print(f"({args.model}, {gpt_query_count} queries)")
    print()
    print("Sources:")
    for source, title in sources:
        print(f"* [{title}]({source})")

if __name__ == "__main__":
    sys.exit(main())
