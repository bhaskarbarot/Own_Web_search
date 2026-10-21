
Use this benchmark to evaluate `own_web_search_engine` against Google Search, Brave Search, and Firecrawl where comparable capabilities are available.

The benchmark tests whether a search system can find relevant pages, rank them well, return useful source content, handle freshness and ambiguity, and help an AI agent complete real tasks.

> **Comparison note:** Google and Brave provide search capabilities; Firecrawl focuses on web crawling, search-related workflows, and content extraction. Compare equivalent capabilities separately. Do not treat full-page extraction as identical to search-result ranking.

## How to run the benchmark

1. Submit the same query to each provider.
2. Save the top 10 results where available, including title, URL, snippet/content, rank, timestamp, and latency.
3. Judge relevance independently of which provider returned the result.
4. Record failures, stale results, broken URLs, unsupported claims, and missing sources.
5. Repeat tests after changes to crawling, indexing, query processing, ranking, or extraction.

For date-sensitive tests, record the run date and distinguish the date an event happened from the page's publication or update date.

---

## 1. Coding agent

**Purpose:** Find repositories, fix bugs, understand libraries, and implement features.

| ID | Search query | What to verify |
|---|---|---|
| C01 | Find open-source Ruby on Rails projects that use React and TypeScript and have open issues suitable for a first-time contributor. | Correct language, framework, and issue status |
| C02 | Find GitHub repositories with open bugs related to PostgreSQL connection pooling. | Relevant repositories and actual open issues |
| C03 | Search for official LangGraph documentation explaining how to implement human-in-the-loop approval. | Official documentation and relevant passages |
| C04 | Find Python libraries for extracting the main article text from a webpage, excluding navigation and advertisements. | Relevant libraries and capabilities |
| C05 | Find open-source implementations of semantic search using PostgreSQL and pgvector. | Working repositories, not just tutorials |
| C06 | Find the official documentation for React's `useEffect` hook and explain when cleanup is required. | Correct official source |
| C07 | Search GitHub for projects implementing browser-based terminal emulators with xterm.js. | Relevant repositories and implementation examples |
| C08 | Find recent GitHub issues reporting memory leaks in Python asynchronous applications. | Real issues, dates, and technical relevance |

**Agent task:**  
> I am building a coding agent. Find three open-source Rails + React + TypeScript projects with genuinely open issues. Select an issue involving a bug rather than a feature request. Return the repository, issue URL, issue status, and a short explanation of why the issue is suitable.

**Success checks:** Verify that repositories and issues exist, the issue is still open, and evidence supports each claim. Do not accept invented URLs or reproduction steps.

## 2. Research agent

**Purpose:** Research technical subjects using reliable sources.

| ID | Search query | What to verify |
|---|---|---|
| R01 | Compare traditional keyword search with semantic search and hybrid search. | Accurate technical distinctions |
| R02 | Find research papers on retrieval-augmented generation published in 2025 or 2026. | Publication dates and real papers |
| R03 | Find research on evaluating search-engine relevance using NDCG, MRR, and Recall@K. | Relevant papers and correct terminology |
| R04 | Find studies on how search result quality affects large language model responses. | Evidence from credible research |
| R05 | Explain the difference between web crawling, indexing, ranking, and content extraction using authoritative sources. | Coverage of all four concepts |
| R06 | Find open-source benchmarks for evaluating information retrieval systems. | Actual benchmark datasets and licenses |
| R07 | Find research comparing dense retrieval with BM25 for information retrieval. | Relevant studies and experimental results |
| R08 | Find documented limitations of using LLMs as search relevance evaluators. | Real limitations supported by evidence |

**Agent task:**  
> Research whether hybrid search is better than pure vector search for a technical documentation search engine. Find relevant research, compare the approaches, and provide source URLs and evidence for each major conclusion.

**Success checks:** Results should support conclusions, not merely mention matching keywords.

## 3. AI and machine-learning agent

**Purpose:** Find models, APIs, frameworks, and implementation details.

| ID | Search query | What to verify |
|---|---|---|
| A01 | Find free or open-weight LLMs suitable for CPU inference on a machine with 16 GB RAM. | Model requirements and realistic hardware compatibility |
| A02 | Find official documentation for the Gemini embedding models API. | Correct provider documentation |
| A03 | Compare Groq and Google Gemini APIs for building an AI assistant, including rate limits and pricing. | Current, date-sensitive details |
| A04 | Find Python frameworks for building multi-agent systems with tool calling and state persistence. | Actual capabilities and documentation |
| A05 | Find methods for evaluating hallucinations in retrieval-augmented generation systems. | Useful evaluation methodologies |
| A06 | Find open-source reranking models for improving search result relevance. | Real models, repositories, and licenses |
| A07 | Find examples of structured JSON output from LLM APIs, including schema validation. | Working documentation and examples |
| A08 | Find ways to cache LLM responses using Redis while avoiding incorrect cache reuse. | Practical caching approaches and limitations |

## 4. Business research agent

**Purpose:** Research companies, markets, competitors, and business opportunities.

| ID | Search query | What to verify |
|---|---|---|
| B01 | Find open-source ERP systems used for accounting, inventory, sales, and invoicing. | Actual ERP capabilities |
| B02 | Compare ERPNext and Odoo for small Indian retail businesses. | Relevant product features and India-specific support |
| B03 | Find AI-powered accounting automation products designed for Indian accountants. | Real products and verifiable features |
| B04 | Find official documentation on GST e-invoicing requirements for Indian businesses. | Authoritative Indian government sources |
| B05 | Find competitors offering AI agents for bookkeeping and accounting data entry. | Real competitors, not invented businesses |
| B06 | Find open-source point-of-sale systems that integrate inventory and accounting. | Repository activity and integration capabilities |
| B07 | Find public pricing pages for accounting automation software aimed at small businesses. | Actual pricing and currency |
| B08 | Find case studies measuring the time saved by accounting automation. | Quantified results and original sources |

**Agent task:**  
> I want to build an AI accounting assistant for Indian accountants. Identify existing competitors, open-source accounting platforms, GST integration requirements, and available APIs. Separate verified facts from assumptions and cite the original sources.

**Success checks:** Retrieve evidence from multiple sites and distinguish verified facts from assumptions.

## 5. News and current-events agent

**Purpose:** Find recent developments without presenting outdated information as current.

| ID | Search query | What to verify |
|---|---|---|
| N01 | What are the latest major AI model releases announced this week? | Publication dates and announcement sources |
| N02 | Find the latest official announcements about Python releases in 2026. | Current version and official release information |
| N03 | Find recent security vulnerabilities disclosed for PostgreSQL in the last 30 days. | CVE identifiers, dates, and affected versions |
| N04 | What changes have Google and Brave announced about their search APIs in 2026? | Current official announcements |
| N05 | Find recent developments in open-source AI agents published in the last seven days. | Recency and primary sources |
| N06 | Find the latest official Ubuntu security advisories affecting Ubuntu 24.04. | Relevant advisories and affected packages |
| N07 | Find recent changes to GitHub Actions pricing or usage limits. | Current documentation and announcement dates |
| N08 | Find recent news about AI regulation in India, prioritizing government announcements. | Reliable sources and correct chronology |

These are test queries, not claims that a particular announcement or vulnerability exists. Check event dates separately from publication and update dates.

## 6. Documentation and troubleshooting agent

**Purpose:** Solve real technical problems using official documentation and reliable explanations.

| ID | Search query | What to verify |
|---|---|---|
| T01 | Docker Desktop on Ubuntu does not open after installation. Find official troubleshooting steps. | Correct OS-specific instructions |
| T02 | Git reports `fatal: unable to get credential storage lock`. Find likely causes and safe fixes. | Relevant troubleshooting information |
| T03 | PostgreSQL reports `remaining connection slots are reserved`. Find solutions involving connection pooling. | Accurate diagnosis and remedies |
| T04 | Python raises `ModuleNotFoundError` inside Docker although the package is installed locally. Explain how to diagnose it. | Container-specific troubleshooting |
| T05 | Find the official Supabase dashboard instructions for exporting a database backup. | Correct dashboard and export documentation |
| T06 | Find official instructions for configuring GitHub Actions secrets. | Current GitHub documentation |
| T07 | Explain how to resolve `nvidia-smi: command not found` on Ubuntu when the machine may not have an NVIDIA GPU. | Correct diagnosis without assuming a GPU exists |
| T08 | Find solutions for React components repeatedly triggering `useEffect`. | Relevant causes, dependency rules, and cleanup |

**Success checks:** Search should work with exact error messages and return relevant documentation rather than generic pages.

## 7. Product comparison agent

**Purpose:** Compare products using specifications, capabilities, pricing, and limitations.

| ID | Search query | What to verify |
|---|---|---|
| P01 | Compare Google Search, Brave Search API, and Firecrawl for building an AI research agent. | Correctly distinguishes their capabilities |
| P02 | Compare Elasticsearch, OpenSearch, and Typesense for a small self-hosted search engine. | Relevant features and deployment requirements |
| P03 | Compare Playwright and Selenium for automated browser testing in Python. | Accurate technical differences |
| P04 | Compare PostgreSQL full-text search with pgvector semantic search. | Clear explanation of trade-offs |
| P05 | Compare LangGraph and CrewAI for stateful, multi-agent workflows. | Actual framework capabilities |
| P06 | Compare Redis and Memcached for caching API responses. | Appropriate use cases and limitations |
| P07 | Compare open-source web crawling frameworks for large-scale crawling. | Performance, architecture, and licensing evidence |
| P08 | Compare popular open-source observability tools for AI applications. | Real capabilities, integrations, and licensing |

**Success checks:** Results should support a balanced comparison across all products rather than covering just one.

## 8. Academic and educational agent

**Purpose:** Find reliable educational material and primary sources.

| ID | Search query | What to verify |
|---|---|---|
| E01 | Find beginner-friendly tutorials explaining how BM25 ranks documents. | Accurate explanations and useful examples |
| E02 | Find university lectures explaining information retrieval and search ranking. | Educational quality and original institutions |
| E03 | Find official documentation explaining HTTP status codes 429 and 503. | Correct definitions and handling |
| E04 | Find papers introducing or evaluating the MTEB embedding benchmark. | Original research and benchmark details |
| E05 | Find resources explaining precision, recall, and F1 score with examples. | Mathematical accuracy |
| E06 | Find courses teaching web crawling and search-engine indexing. | Course availability and curriculum |
| E07 | Find explanations of the PageRank algorithm from reliable sources. | Correct algorithmic concepts |
| E08 | Find academic work on multilingual information retrieval. | Relevant papers and languages covered |

## 9. E-commerce and shopping agent

**Purpose:** Find products and compare purchase options.

| ID | Search query | What to verify |
|---|---|---|
| S01 | Find 16 GB RAM laptops under ₹50,000 available in India. | Actual specifications, prices, and availability |
| S02 | Compare mini PCs suitable for running CPU-based LLMs locally. | RAM, processor, upgradeability, and price |
| S03 | Find external SSDs suitable for storing large machine-learning datasets. | Capacity, interface, and real specifications |
| S04 | Find laptops with 32 GB RAM that can run Docker and multiple development containers. | Real hardware configurations |
| S05 | Find open-source website analytics tools that can be self-hosted. | Actual software and licensing |
| S06 | Compare affordable UPS devices suitable for a desktop computer in India. | Capacity, power requirements, and pricing |
| S07 | Find mechanical keyboards available in India with Linux-compatible layouts. | Actual product specifications |
| S08 | Find cloud GPU providers with published hourly pricing for LLM inference. | Current prices and GPU specifications |

**Success checks:** Results should include real products and reliable purchase sources. Record when prices and availability were checked.

## 10. Local and location-aware agent

**Purpose:** Find useful businesses and services in a specified location. Use Ahmedabad, Gujarat, India, for these tests.

| ID | Search query | What to verify |
|---|---|---|
| L01 | Find coworking spaces in Ahmedabad with monthly pricing. | Actual locations and published prices |
| L02 | Find computer hardware shops in Ahmedabad that sell desktop RAM. | Real businesses and contact details |
| L03 | Find PostgreSQL training institutes in Ahmedabad. | Relevant training services |
| L04 | Find software companies in Ahmedabad hiring junior Python developers. | Current job listings and company details |
| L05 | Find internet service providers serving residential areas in Ahmedabad. | Actual coverage and service availability |
| L06 | Find libraries or quiet study spaces in Ahmedabad with published opening hours. | Location and current hours |
| L07 | Find laptop repair shops in Ahmedabad with reviews and contact information. | Real businesses and review sources |
| L08 | Find local technology meetups or developer events in Ahmedabad this month. | Current event dates and registration details |

**Success checks:** A web result alone does not prove a business is open, a product is in stock, or a job is still available. Distinguish verified details from unconfirmed listings.

## 11. Multi-step autonomous research agent

**Purpose:** Test whether an agent can use search repeatedly to complete a workflow. Run these as workflows, not just single queries.

| ID | Agent task | Searches it needs to perform |
|---|---|---|
| M01 | Find a Python library for extracting webpage content and integrate it into a project. | Find candidate libraries → inspect official documentation → locate installation instructions → find examples |
| M02 | Identify an open-source project with a reproducible bug suitable for fixing. | Find repositories → inspect open issues → verify reproduction steps → locate relevant source files |
| M03 | Research whether a search API is suitable for an AI agent. | Find API documentation → investigate rate limits → examine pricing → identify licensing restrictions |
| M04 | Build a searchable knowledge base from technical documentation. | Find ingestion libraries → compare embedding models → research indexing approaches → find retrieval evaluation methods |
| M05 | Investigate a PostgreSQL performance problem. | Search the error → find official documentation → investigate likely causes → locate safe troubleshooting steps |
| M06 | Identify an open-source accounting platform for Indian businesses. | Find candidate platforms → inspect GST support → verify licensing → find integration documentation |
| M07 | Evaluate the security of an open-source project. | Find the repository → inspect security advisories → check release activity → identify documented vulnerabilities |
| M08 | Recommend a self-hosted search architecture for a small development team. | Compare indexing engines → investigate storage requirements → compare deployment complexity → identify operational trade-offs |

**Success checks:** Measure whether the agent reaches a defensible conclusion using retrieved evidence, not just whether it receives relevant-looking links.

## 12. Difficult, ambiguous, and adversarial search agent

**Purpose:** Expose limitations that easy queries may hide.

| ID | Search query | What to verify |
|---|---|---|
| D01 | jaguar | Handles ambiguity between the animal, car brand, and other meanings |
| D02 | Python | Covers the programming language as well as other meanings |
| D03 | How do I make my website faster? | Returns actionable information rather than generic results |
| D04 | Find the official documentation for a library that was discontinued and replaced by a newer project. | Identifies deprecation and migration information |
| D05 | Search for a nonexistent programming library named `SuperVectorDB9000`. | Avoids fabricating results |
| D06 | Find the original source of a widely repeated technical claim. | Finds primary sources rather than only secondary articles |
| D07 | Find the exact phrase `"unable to get credential storage lock"` in technical documentation. | Exact-phrase matching and relevant results |
| D08 | How can I configure LangGraph to use PostgreSQL for persistent state? | Finds relevant documentation despite different wording |
| D09 | Find an official security advisory for a vulnerability that affects a specific software version, and verify whether the fixed version includes the patch. | Version-specific accuracy and source evidence |
| D10 | Compare two products when reliable sources disagree about their performance. | Preserves conflicting evidence rather than inventing certainty |
| D11 | Find three independent sources discussing the same technical claim and identify where their conclusions disagree. | Cross-source evidence and disagreement handling |
| D12 | Find the official documentation for a feature whose name has changed between two software versions, and identify the equivalent feature in each version. | Version-aware retrieval and documentation accuracy |

---

## 13. Three end-to-end agent profiles

### Agent A: Developer agent

**Goal:** Find a bug in an open-source repository and prepare a fix.

Workflow:

1. Search for suitable GitHub repositories.
2. Find an issue that is still open.
3. Retrieve the issue description and reproduction steps.
4. Find relevant source code and official documentation.
5. Identify a potential fix.
6. Verify the proposed fix against available evidence.

Success criteria:

- The repository exists.
- The issue is genuinely open.
- Source files and documentation are relevant.
- The agent does not invent reproduction steps or claim a fix works without evidence.

### Agent B: Research agent

**Goal:** Determine whether a web search engine is suitable for production AI applications.

Workflow:

1. Search for web search APIs and crawling tools.
2. Find official documentation for each candidate.
3. Research rate limits, pricing, and usage restrictions.
4. Find independent evaluations of result quality.
5. Compare the available evidence.
6. Produce a recommendation with citations.

Success criteria:

- Sources support the comparisons.
- Current prices and limits are not confused with outdated values.
- Vendor claims are distinguished from independent evidence.
- The recommendation follows from the evidence.

### Agent C: Technical troubleshooting agent

**Goal:** Diagnose a developer problem.

**Task prompt:**

> My application uses Python, FastAPI, PostgreSQL, and Docker. The application works locally but sometimes fails with PostgreSQL connection errors in production. Investigate the likely causes and recommend a debugging procedure.

Workflow:

1. Search the exact error message if available.
2. Find official PostgreSQL and database-driver documentation.
3. Research connection pooling and container networking.
4. Identify possible causes and how to distinguish them.
5. Recommend diagnostic commands and safe fixes.
6. Cite sources supporting the recommendations.

Success criteria:

- Considers multiple plausible causes.
- Distinguishes possible causes from confirmed diagnoses.
- Gives technically correct steps.
- Uses relevant documentation rather than relying exclusively on generic blog posts.

---

## 14. Compare search providers

Run the same queries through your engine, Google, Brave, and Firecrawl where the required capability is available. Save the top 10 results per query where possible.

Record:

| Field | What to record |
|---|---|
| Query ID | Example: C01 |
| Provider | Your Engine / Google / Brave / Firecrawl |
| Query | Exact query submitted |
| Result count | Number of results returned |
| Relevant results | Number of useful results in the top 10 |
| Correct URLs | Whether URLs resolve to the expected sources |
| Source quality | Official, primary, reputable secondary, or low-quality |
| Freshness | Whether results meet the query's date requirements |
| Coverage | Whether important parts of the query are covered |
| Latency | Time until usable results are returned |
| Errors | Timeouts, invalid URLs, missing results, or other failures |
| Agent success | Whether the agent completed its task with retrieved evidence |

For reproducibility, record the test date, API configuration, search parameters, and whether the providers received the same query.

### Metrics

#### Precision@10

The proportion of the first 10 results judged relevant.

`Precision@10 = relevant results in top 10 / 10`

If 7 of the top 10 results are relevant, Precision@10 is 0.70.

#### Recall@10

The proportion of known relevant documents retrieved in the first 10 results.

`Recall@10 = relevant documents retrieved / all known relevant documents`

Build a judged reference set first. This is recall against that reference set, not necessarily recall against every relevant page on the web.

#### NDCG@10

Measures ranking quality while giving more weight to relevant results near the top.

#### Latency

Measure time until usable results are returned. Record median and p95 latency across repeated runs.

#### Task success rate

`Task success rate = successfully completed tasks / total tasks × 100`

A search engine may return plausible links but still fail to provide enough evidence for an agent to complete its task.

**Avoid bias:** Judge relevance independently of the provider that returned each result.

---

## 15. Evaluate AI-agent usefulness

Inspect these capabilities for every query:

| Capability | What good performance looks like |
|---|---|
| Query understanding | Understands what the user actually wants |
| Retrieval | Finds genuinely relevant pages |
| Ranking | Places the most useful results near the top |
| Content extraction | Provides readable page content when supported |
| Evidence quality | Preserves source URLs, titles, and relevant text |
| Reliability | Handles empty results, errors, ambiguity, and outdated pages appropriately |

Prioritize relevance, source accuracy, content quality, and task completion before optimizing for raw speed alone.

### Content-quality example

Query:

> Find the official LangGraph documentation explaining how to persist graph state across application restarts using PostgreSQL.

- **Weak:** A page mentions LangGraph and PostgreSQL but does not explain persistence.
- **Acceptable:** Official documentation discusses persistence and checkpoints.
- **Strong:** The result identifies the relevant documentation, provides a useful content excerpt, preserves the source URL, and gives the agent enough information to continue researching.

---

## 16. Recommended execution plan

### Phase 1 — Basic retrieval

- Run C01–C08 and T01–T08.
- Check whether the engine finds relevant, working pages.
- Investigate missing results, irrelevant results, and incorrect URLs.

### Phase 2 — Search quality

- Run research, AI/ML, business, news, comparison, education, shopping, and local queries.
- Check ranking, source quality, freshness, and coverage.
- Pay special attention to queries requiring official sources.

### Phase 3 — AI-agent workflows

- Run M01–M08 and the three agent profiles.
- Evaluate whether retrieved information is sufficient to complete each task.
- Test missing evidence, conflicting sources, and failures.

Keep a record of failures and rerun the same queries after changes to ranking, crawling, extraction, or query processing.

## 17. Permanent benchmark dataset

Maintain a versioned dataset containing:

- 100 fixed queries across the categories above.
- A reference set of relevant URLs for each query.
- Relevance judgments for the top 10 results.
- Expected facts or requirements for objectively verifiable queries.
- Separate multi-step agent tasks.
- Historical results to identify improvements and regressions.

Automate the benchmark when practical and run it whenever you change the search algorithm.

## 18. Implementation notes

- Store each query with a stable ID, category, query text, expected behavior, and freshness requirement.
- Save raw provider responses as well as normalized results.
- Keep provider-specific adapters separate so one provider's response format does not distort the comparison.
- Track result rank, URL, title, snippet or extracted text, retrieval time, and errors.
- Make relevance judgments repeatable. Ideally use human judgments or a carefully reviewed evaluation set.
- For current-events queries, rerun at a known time and store the timestamp.
- Treat HTTP success as different from result relevance.
- Do not count unsupported claims as correct just because the page title looks relevant.
- Use the same query set for regression tests after code changes.

## Important note about benchmark counts

The core list contains **100 individual queries**: 8 each in categories C, R, A, B, N, T, P, E, S, and L (80 total), 8 multi-step tasks (M01–M08), and 12 difficult queries (D01–D12). The three end-to-end agent profiles are additional workflow tests and are not included in the 100-query count.
'''


1. Test your search engine with these 12 AI-agent types
I've organized the tests into 12 categories with 100 search queries. They cover everyday searches, coding, research, current information, business, and more difficult queries.

Use the same queries for each search provider. This gives you a repeatable benchmark instead of judging results based on a few examples.
Agent 1: Coding agent
Purpose: Find repositories, fix bugs, understand libraries, and implement features.
ID	Search query	What to verify
C01	Find open-source Ruby on Rails projects that use React and TypeScript and have open issues suitable for a first-time contributor.	Correct language, framework, and issue status
C02	Find GitHub repositories with open bugs related to PostgreSQL connection pooling.	Relevant repositories and actual open issues
C03	Search for official LangGraph documentation explaining how to implement human-in-the-loop approval.	Official documentation and relevant passages
C04	Find Python libraries for extracting the main article text from a webpage, excluding navigation and advertisements.	Relevant libraries and capabilities
C05	Find open-source implementations of semantic search using PostgreSQL and pgvector.	Working repositories, not just tutorials
C06	Find the official documentation for React's useEffect hook and explain when cleanup is required.	Correct official source
C07	Search GitHub for projects implementing browser-based terminal emulators with xterm.js.	Relevant repositories and implementation examples
C08	Find recent GitHub issues reporting memory leaks in Python asynchronous applications.	Real issues, dates, and technical relevance


Agent task example
I am building a coding agent. Find three open-source Rails + React + TypeScript projects with genuinely open issues. Select an issue involving a bug rather than a feature request. Return the repository, issue URL, issue status, and a short explanation of why the issue is suitable.

Your engine should retrieve evidence supporting every important claim. It should not invent repositories, issue statuses, or URLs.
Agent 2: Research agent
Purpose: Research technical subjects using reliable sources.
ID	Search query	What to verify
R01	Compare traditional keyword search with semantic search and hybrid search.	Accurate technical distinctions
R02	Find research papers on retrieval-augmented generation published in 2025 or 2026.	Publication dates and real papers
R03	Find research on evaluating search-engine relevance using NDCG, MRR, and Recall@K.	Relevant papers and correct terminology
R04	Find studies on how search result quality affects large language model responses.	Evidence from credible research
R05	Explain the difference between web crawling, indexing, ranking, and content extraction using authoritative sources.	Coverage of all four concepts
R06	Find open-source benchmarks for evaluating information retrieval systems.	Actual benchmark datasets and licenses
R07	Find research comparing dense retrieval with BM25 for information retrieval.	Relevant studies and experimental results
R08	Find documented limitations of using LLMs as search relevance evaluators.	Real limitations supported by evidence


Agent task example
Research whether hybrid search is better than pure vector search for a technical documentation search engine. Find relevant research, compare the approaches, and provide source URLs and evidence for each major conclusion.

The engine should return evidence that supports the conclusion, not merely pages containing the words "hybrid search."
Agent 3: AI and machine-learning agent
Purpose: Find models, APIs, frameworks, and implementation details.
ID	Search query	What to verify
A01	Find free or open-weight LLMs suitable for CPU inference on a machine with 16 GB RAM.	Model requirements and realistic hardware compatibility
A02	Find official documentation for the Gemini embedding models API.	Correct provider documentation
A03	Compare Groq and Google Gemini APIs for building an AI assistant, including rate limits and pricing.	Current, date-sensitive details
A04	Find Python frameworks for building multi-agent systems with tool calling and state persistence.	Actual capabilities and documentation
A05	Find methods for evaluating hallucinations in retrieval-augmented generation systems.	Useful evaluation methodologies
A06	Find open-source reranking models for improving search result relevance.	Real models, repositories, and licenses
A07	Find examples of structured JSON output from LLM APIs, including schema validation.	Working documentation and examples
A08	Find ways to cache LLM responses using Redis while avoiding incorrect cache reuse.	Practical caching approaches and limitations


Agent 4: Business research agent
Purpose: Research companies, markets, competitors, and business opportunities.
ID	Search query	What to verify
B01	Find open-source ERP systems used for accounting, inventory, sales, and invoicing.	Actual ERP capabilities
B02	Compare ERPNext and Odoo for small Indian retail businesses.	Relevant product features and India-specific support
B03	Find AI-powered accounting automation products designed for Indian accountants.	Real products and verifiable features
B04	Find official documentation on GST e-invoicing requirements for Indian businesses.	Authoritative Indian government sources
B05	Find competitors offering AI agents for bookkeeping and accounting data entry.	Real competitors, not invented businesses
B06	Find open-source point-of-sale systems that integrate inventory and accounting.	Repository activity and integration capabilities
B07	Find public pricing pages for accounting automation software aimed at small businesses.	Actual pricing and currency
B08	Find case studies measuring the time saved by accounting automation.	Quantified results and original sources


Agent task example
I want to build an AI accounting assistant for Indian accountants. Identify existing competitors, open-source accounting platforms, GST integration requirements, and available APIs. Separate verified facts from assumptions and cite the original sources.

This tests whether your engine can retrieve information across several different websites and support a useful business decision.
Agent 5: News and current-events agent
Purpose: Find recent developments without returning outdated information as current.
ID	Search query	What to verify
N01	What are the latest major AI model releases announced this week?	Publication dates and announcement sources
N02	Find the latest official announcements about Python releases in 2026.	Current version and official release information
N03	Find recent security vulnerabilities disclosed for PostgreSQL in the last 30 days.	CVE identifiers, dates, and affected versions
N04	What changes have Google and Brave announced about their search APIs in 2026?	Current official announcements
N05	Find recent developments in open-source AI agents published in the last seven days.	Recency and primary sources
N06	Find the latest official Ubuntu security advisories affecting Ubuntu 24.04.	Relevant advisories and affected packages
N07	Find recent changes to GitHub Actions pricing or usage limits.	Current documentation and announcement dates
N08	Find recent news about AI regulation in India, prioritizing government announcements.	Reliable sources and correct chronology


Important: These are test queries, not claims that a particular announcement or vulnerability exists.

For every query, test whether your engine distinguishes the publication date from the date of the event. An old article updated today should not automatically outrank a genuinely new announcement.
Agent 6: Documentation and troubleshooting agent
Purpose: Solve real technical problems using official documentation and reliable explanations.
ID	Search query	What to verify
T01	Docker Desktop on Ubuntu does not open after installation. Find official troubleshooting steps.	Correct OS-specific instructions
T02	Git reports fatal: unable to get credential storage lock. Find likely causes and safe fixes.	Relevant troubleshooting information
T03	PostgreSQL reports remaining connection slots are reserved. Find solutions involving connection pooling.	Accurate diagnosis and remedies
T04	Python raises ModuleNotFoundError inside Docker although the package is installed locally. Explain how to diagnose it.	Container-specific troubleshooting
T05	Find the official Supabase dashboard instructions for exporting a database backup.	Correct dashboard and export documentation
T06	Find official instructions for configuring GitHub Actions secrets.	Current GitHub documentation
T07	Explain how to resolve nvidia-smi: command not found on Ubuntu when the machine may not have an NVIDIA GPU.	Correct diagnosis without assuming a GPU exists
T08	Find solutions for React components repeatedly triggering useEffect.	Relevant causes, dependency rules, and cleanup


A good search engine should retrieve relevant answers even when the query contains a technical error message.
Agent 7: Product comparison agent
Purpose: Compare products based on specifications, capabilities, pricing, and limitations.
ID	Search query	What to verify
P01	Compare Google Search, Brave Search API, and Firecrawl for building an AI research agent.	Correctly distinguishes their capabilities
P02	Compare Elasticsearch, OpenSearch, and Typesense for a small self-hosted search engine.	Relevant features and deployment requirements
P03	Compare Playwright and Selenium for automated browser testing in Python.	Accurate technical differences
P04	Compare PostgreSQL full-text search with pgvector semantic search.	Clear explanation of trade-offs
P05	Compare LangGraph and CrewAI for stateful, multi-agent workflows.	Actual framework capabilities
P06	Compare Redis and Memcached for caching API responses.	Appropriate use cases and limitations
P07	Compare open-source web crawling frameworks for large-scale crawling.	Performance, architecture, and licensing evidence
P08	Compare popular open-source observability tools for AI applications.	Real capabilities, integrations, and licensing


For comparisons, test whether your engine finds enough evidence to compare each option fairly rather than returning five results about only one product.
Agent 8: Academic and educational agent
Purpose: Find reliable educational material and primary sources.
ID	Search query	What to verify
E01	Find beginner-friendly tutorials explaining how BM25 ranks documents.	Accurate explanations and useful examples
E02	Find university lectures explaining information retrieval and search ranking.	Educational quality and original institutions
E03	Find official documentation explaining HTTP status codes 429 and 503.	Correct definitions and handling
E04	Find papers introducing or evaluating the MTEB embedding benchmark.	Original research and benchmark details
E05	Find resources explaining precision, recall, and F1 score with examples.	Mathematical accuracy
E06	Find courses teaching web crawling and search-engine indexing.	Course availability and curriculum
E07	Find explanations of the PageRank algorithm from reliable sources.	Correct algorithmic concepts
E08	Find academic work on multilingual information retrieval.	Relevant papers and languages covered


Agent 9: E-commerce and shopping agent
Purpose: Find products and compare purchase options.
ID	Search query	What to verify
S01	Find 16 GB RAM laptops under ₹50,000 available in India.	Actual specifications, prices, and availability
S02	Compare mini PCs suitable for running CPU-based LLMs locally.	RAM, processor, upgradeability, and price
S03	Find external SSDs suitable for storing large machine-learning datasets.	Capacity, interface, and real specifications
S04	Find laptops with 32 GB RAM that can run Docker and multiple development containers.	Real hardware configurations
S05	Find open-source website analytics tools that can be self-hosted.	Actual software and licensing
S06	Compare affordable UPS devices suitable for a desktop computer in India.	Capacity, power requirements, and pricing
S07	Find mechanical keyboards available in India with Linux-compatible layouts.	Actual product specifications
S08	Find cloud GPU providers with published hourly pricing for LLM inference.	Current prices and GPU specifications


For shopping queries, test whether your engine returns real products and trustworthy purchase sources, not just general articles.
Agent 10: Local and location-aware agent
Purpose: Find useful businesses and services in a specified location.

Use Ahmedabad, Gujarat, as the location for these tests.
ID	Search query	What to verify
L01	Find coworking spaces in Ahmedabad with monthly pricing.	Actual locations and published prices
L02	Find computer hardware shops in Ahmedabad that sell desktop RAM.	Real businesses and contact details
L03	Find PostgreSQL training institutes in Ahmedabad.	Relevant training services
L04	Find software companies in Ahmedabad hiring junior Python developers.	Current job listings and company details
L05	Find internet service providers serving residential areas in Ahmedabad.	Actual coverage and service availability
L06	Find libraries or quiet study spaces in Ahmedabad with published opening hours.	Location and current hours
L07	Find laptop repair shops in Ahmedabad with reviews and contact information.	Real businesses and review sources
L08	Find local technology meetups or developer events in Ahmedabad this month.	Current event dates and registration details


Important: A web search alone cannot guarantee that a business is open, a product is in stock, or a job is still available. Test whether your engine distinguishes verified information from unconfirmed listings.
Agent 11: Multi-step autonomous research agent
This category is especially important for your project because an AI agent often needs to perform several searches before it can complete a task.

These tests should be executed as workflows rather than as single queries.
ID	Agent's task	Searches it needs to perform
M01	Find a Python library for extracting webpage content and integrate it into a project.	Find candidate libraries → inspect official documentation → locate installation instructions → find examples
M02	Identify an open-source project with a reproducible bug suitable for fixing.	Find repositories → inspect open issues → verify reproduction steps → locate relevant source files
M03	Research whether a search API is suitable for an AI agent.	Find API documentation → investigate rate limits → examine pricing → identify licensing restrictions
M04	Build a searchable knowledge base from technical documentation.	Find ingestion libraries → compare embedding models → research indexing approaches → find retrieval evaluation methods
M05	Investigate a PostgreSQL performance problem.	Search the error → find official documentation → investigate likely causes → locate safe troubleshooting steps
M06	Identify an open-source accounting platform for Indian businesses.	Find candidate platforms → inspect GST support → verify licensing → find integration documentation
M07	Evaluate the security of an open-source project.	Find the repository → inspect security advisories → check release activity → identify documented vulnerabilities
M08	Recommend a self-hosted search architecture for a small development team.	Compare indexing engines → investigate storage requirements → compare deployment complexity → identify operational trade-offs


For each workflow, measure whether your search engine helps the agent reach a defensible conclusion, not just whether it returns relevant-looking links.
Agent 12: Difficult, ambiguous, and adversarial search agent
Purpose: Find the limitations of your engine.
ID	Search query	What to verify
D01	jaguar	Does the engine handle ambiguity between the animal, car brand, and other meanings?
D02	Python	Does it cover the programming language as well as other meanings?
D03	How do I make my website faster?	Does it return useful, actionable information rather than generic results?
D04	Find the official documentation for a library that was discontinued and replaced by a newer project.	Can it identify deprecation and migration information?
D05	Search for a nonexistent programming library named SuperVectorDB9000.	Does it avoid fabricating results?
D06	Find the original source of a widely repeated technical claim.	Can it identify primary sources instead of only secondary articles?
D07	Find the exact phrase "unable to get credential storage lock" in technical documentation.	Exact phrase matching and relevant results
D08	How can I configure LangGraph to use PostgreSQL for persistent state?	Can it find relevant documentation despite different wording?
D09	Find an official security advisory for a vulnerability that affects a specific software version, and verify whether the fixed version includes the patch.	Version-specific accuracy and source evidence
D10	Compare two products when reliable sources disagree about their performance.	Does it preserve conflicting evidence rather than inventing certainty?


These queries are particularly valuable because a search engine can appear excellent on easy queries while failing badly on ambiguous or difficult ones.
2. Add these two tests to complete the 100-query benchmark
ID	Search query	What to verify
D11	Find three independent sources discussing the same technical claim and identify where their conclusions disagree.	Cross-source evidence and disagreement handling
D12	Find the official documentation for a feature whose name has changed between two software versions, and identify the equivalent feature in each version.	Version-aware retrieval and documentation accuracy


You now have 100 queries across 12 categories.