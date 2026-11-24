# News: topic or just the latest, by similarity

The News agent has to decide whether a question is a plain request for news ("latest news on JNJ") or has a topic ("news related to the housing market", "NVDA news about export restrictions"). A plain request is answered from the newest headlines. A question with a topic gets a similarity search over the indexed stories, with Tavily web news when the index has too few.

Before this change, the decision came from the words left over after a stop-word list, and from the LLM's `topic` field. Both failed in practice:
- "related" was not on the list, so "What is the latest news related to JNJ?" became a topic search for "related".
- The LLM gave no topic for "news related to the housing market" (it read it as "the market"), so that question got the stock market's headlines.

## How it works now (`src/workflow/news.py`)

1. `residual(text, mentions)`: the proofread question without the companies and markets it names, its time window ("last 10 days") and its count ("latest 5").
2. `generic_score`: the highest cosine similarity (bge-small, the knowledge base's embedder) between the residual and a few plain news requests (`GENERIC_REQUESTS`: "latest news", "any updates", "what's new", "news regarding it", …).
3. If the score is at least `GENERIC_MIN` = 0.81, it is a plain request and gets the latest headlines. Below that, it is a topic and gets a similarity search, using the residual as the query when a ticker filter applies and the whole question otherwise.

Without embeddings (tests), the old word rules decide.

## Measurements (bge-small-en-v1.5, 2026-11-23)

Residual → best match → similarity:

| Question | Residual | Score | Decision |
|---|---|---|---|
| What is the latest news related to JNJ? | What is the latest news related to ? | 0.946 | latest |
| What's the latest news? | What's the latest news? | 0.958 | latest |
| What is the latest news about AAPL over the last 10 days? | What is the latest news about ? | 0.954 | latest |
| Are there any news about JPMorgan? | Are there any news about ? | 0.897 | latest |
| what's in the news? | what's in the news? | 0.897 | latest |
| Can you show the latest 5 news about AAPL? | Can you show the latest news about ? | 0.892 | latest |
| what's the latest on gold? | what's the latest on ? | 0.875 | latest |
| what's new with Tesla? | what's new with ? | 0.866 | latest |
| What is the news related to JNJ from the last 10 days? | What is the news related to ? | 0.835 | latest |
| news regarding Apple | news regarding | 0.824 | latest |
| what happened to NVDA today | what happened to | 0.822 | latest |
| Any updates on Nvidia? | Any updates on ? | 0.819 | latest |
| any earnings news for MSFT? | any earnings news ? | 0.790 | topic |
| How does the latest news affect my portfolio? | (unchanged) | 0.789 | topic |
| What is the news related to the housing market? | (unchanged) | 0.781 | topic |
| job market news | (unchanged) | 0.773 | topic |
| Tesla lawsuit news | lawsuit news | 0.750 | topic |
| What moved the stock market this week? | What moved the stock market ? | 0.707 | topic |
| Why did AAPL drop today? any news? | Why did drop ? any news? | 0.707 | topic |
| news about interest rates and the Fed this week | news about interest rates and the Fed | 0.701 | topic |
| NVDA news about export restrictions | news about export restrictions | 0.697 | topic |

The gap is narrow: plain requests score at least 0.819 and questions with a topic at most 0.790. A short topic word in an otherwise generic sentence ("any earnings news") sits close to the line. Re-measure before changing the embedding model or the prototypes.
