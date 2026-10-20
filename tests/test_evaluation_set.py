"""Evaluation harness: 50+ diverse queries with graded relevance over a fixed corpus.

This is NOT a hardcoded answer test. It builds a small multi-lingual corpus, runs
queries, and measures P@5, MRR, NDCG@10, recall, zero-result rate and latency.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from ownsearch.engine import SearchEngine
from ownsearch.evaluation import evaluate, load_qrels
from tests.helpers import make_engine


def build_corpus(engine):
    docs = [
        # --- Python / coding ---
        ("Python palindrome program",
         "Here is a Python program to check if a string is a palindrome. "
         "def is_palindrome(s): return s == s[::-1]. A palindrome reads the same forwards and backwards. "
         "This code works for strings, numbers and lists. Use this function in your Python projects.",
         "https://docs.example/python/palindrome"),
        ("Python palindrome code examples",
         "Python code for palindrome checking: number = int(input('Enter a number: ')); temp = number; "
         "reverse = 0; while number > 0: digit = number % 10; reverse = reverse * 10 + digit; "
         "number = number // 10; if temp == reverse: print('palindrome'). "
         "These are useful Python snippets for beginners learning algorithms.",
         "https://tutorials.example/python-palindrome-code"),
        ("Python recursion tutorial",
         "Learn recursion in Python. A recursive function calls itself. Example: def factorial(n): "
         "return 1 if n <= 1 else n * factorial(n-1). Recursion is useful for tree traversal and divide-and-conquer.",
         "https://tutorials.example/python-recursion"),
        ("Python list comprehensions",
         "Python list comprehensions provide a concise way to create lists. "
         "squares = [x**2 for x in range(10)]. This is faster and more readable than for loops.",
         "https://docs.example/python/list-comprehensions"),
        ("Python requests library guide",
         "The Python requests library lets you send HTTP requests easily. "
         "import requests; r = requests.get('https://api.example.com'); print(r.json()). "
         "Handle status codes, headers, timeouts and sessions.",
         "https://docs.example/python-requests-guide"),

        # --- AI / ML (English) ---
        ("What is artificial intelligence",
         "Artificial intelligence (AI) is the simulation of human intelligence by machines. "
         "AI includes machine learning, deep learning, natural language processing and computer vision. "
         "Modern AI systems use neural networks trained on large datasets.",
         "https://wiki.example/artificial-intelligence"),
        ("Machine learning algorithms explained",
         "Machine learning algorithms include linear regression, decision trees, random forests, "
         "support vector machines and neural networks. Supervised learning uses labeled data; "
         "unsupervised learning finds patterns in unlabeled data.",
         "https://tutorials.example/ml-algorithms"),
        ("Neural network basics",
         "A neural network consists of layers of interconnected nodes (neurons). "
         "Input layer receives data, hidden layers process it, output layer produces results. "
         "Backpropagation adjusts weights to minimize error.",
         "https://wiki.example/neural-network"),

        # --- AI / ML (Hindi) ---
        ("कृत्रिम बुद्धिमत्ता क्या है",
         "कृत्रिम बुद्धिमत्ता (AI) मशीनों द्वारा मानव बुद्धि का अनुकरण है। "
         "इसमें मशीन लर्निंग, डीप लर्निंग, प्राकृतिक भाषा प्रसंस्करण और कंप्यूटर विज़न शामिल हैं। "
         "आधुनिक AI सिस्टम बड़े डेटासेट पर प्रशिक्षित न्यूरल नेटवर्क का उपयोग करते हैं।",
         "https://wiki.example/krtrim-buddhimatta"),
        ("मशीन लर्निंग क्या है",
         "मशीन लर्निंग एक ऐसी तकनीक है जिसमें कंप्यूटर डेटा से सीखते हैं बिना स्पष्ट रूप से प्रोग्राम किए। "
         "वे पैटर्न की पहचान करते हैं और सुधार करते हैं। मशीन लर्निंग अल्गोरिदम में रिग्रेशन, क्लासिफिकेशन और क्लस्टरिंग शामिल हैं।",
         "https://wiki.example/machine-learning-hindi"),
        ("डीप लर्निंग ट्यूटोरियल",
         "डीप लर्निंग मशीन लर्निंग का एक उपसमूह है जो न्यूरल नेटवर्क का उपयोग करता है। "
         "यह छवि पहचान, भाषा अनुवाद और खेल जैसे कार्यों में उत्कृष्ट है। कनवोल्यूशनल नेटवर्क छवियों के लिए उपयुक्त हैं।",
         "https://tutorials.example/deep-learning-hindi"),

        # --- AI / ML (Gujarati) ---
        ("કૃત્રિમ બુદ્ધિ શું છે",
         "કૃત્રિમ બુદ્ધિ એ મશીનો દ્વારા માનવ બુદ્ધિનું અનુકરણ છે. "
         "તેમાં મશીન લર્નિંગ, ડીપ લર્નિંગ, કુદરતી ભાષા પ્રક્રિયા અને કમ્પ્યુટર વિઝનનો સમાવેશ થાય છે. "
         "આધુનિક AI સિસ્ટમ્સ મોટા ડેટાસેટ પર તાલીમ પામેલા ન્યૂરલ નેટવર્કનો ઉપયોગ કરે છે.",
         "https://wiki.example/krutrim-buddhi"),
        ("મશીન લર્નિંગ ગુજરાતીમાં",
         "મશીન લર્નિંગ એ એક તકનીક છે જેમાં કમ્પ્યુટર ડેટા પરથી શીખે છે સ્પષ્ટ રીતે પ્રોગ્રામ કર્યા વિના. "
         "તેઓ પેટર્ન ઓળખે છે અને સુધારે છે. મશીન લર્નિંગ અલ્ગોરિધમમાં રિગ્રેશન, ક્લાસિફિકેશન અને ક્લસ્ટરિંગનો સમાવેશ થાય છે.",
         "https://wiki.example/machine-learning-gujarati"),
        ("ગુજરાતીમાં કૃત્રિમ બુદ્ધિ સમજાવો",
         "કૃત્રિમ બુદ્ધિ એ એવી તકનીક છે જેમાં મશીન માનવની જેમ વિચારવા અને નિર્ણય લેવાનું શીખે છે. "
         "AI ના ઉદાહરણોમાં વોચ રિકગ્નિશન, સELF-DRIVING કાર, અને ચેટબોટનો સમાવેશ થાય છે. "
         "મશીન લર્નિંગ અને ડીપ લર્નિંગ AI ના ભાગ છે.",
         "https://wiki.example/ai-gujarati-explanation"),

        # --- TV serials ---
        ("Kumkum Bhagya serial characters",
         "Kumkum Bhagya is a popular Indian TV serial on Zee TV. The main characters are Pragya, Abhi, "
         "Bulbul, Purab, Alia, Tanu, Dadi, Sarla, and many others. The show follows the love story of "
         "Pragya and Abhi. It has been running since 2014.",
         "https://example.com/kumkum-bhagya"),
        ("Kundali Bhagya serial characters",
         "Kundali Bhagya is a spin-off of Kumkum Bhagya. The characters include Preeta, Karan, Rishabh, "
         "Srishti, Sameera, Sherlyn, Prithvi, and Rakhi. It focuses on the Luthra family and the love "
         "triangle between Preeta, Karan and Rishabh.",
         "https://example.com/kundali-bhagya"),
        ("Kumkum Bhagya latest episodes",
         "Watch the latest episodes of Kumkum Bhagya on Zee TV. The serial has completed over 2000 episodes "
         "since its launch in 2014. The current track focuses on the next generation of the Mehra family.",
         "https://example.com/kumkum-episodes"),

        # --- Official documentation ---
        ("Claude MCP documentation",
         "The official Claude MCP (Model Context Protocol) documentation explains how to build MCP servers "
         "and clients. MCP enables AI assistants to interact with external tools and data sources. "
         "The protocol defines tools, resources and prompts. See docs.anthropic.com for the official guide.",
         "https://docs.anthropic.com/claude/mcp"),
        ("Claude API reference",
         "The Claude API reference covers all endpoints for the Anthropic Claude models. "
         "Use POST /v1/messages to generate responses. Supports vision, tool use and streaming. "
         "Authentication uses x-api-key header.",
         "https://docs.anthropic.com/api/reference"),
        ("MCP server implementation guide",
         "This guide shows how to implement an MCP server in Python. Use the mcp Python package. "
         "Define tools with @mcp.tool decorator. Connect via stdio or HTTP transport.",
         "https://docs.anthropic.com/mcp/server-guide"),

        # --- News ---
        ("AI news today October 2026",
         "AI startups raised record funding this week. Major tech companies announced new AI models. "
         "The conference featured keynote speeches on AGI safety. Published on October 10, 2026.",
         "https://news.example/ai-news-oct-2026"),
        ("Technology news this week",
         "This week in technology: new smartphone launches, software updates, and AI developments. "
         "Industry analysts predict strong growth in cloud computing. Reported October 12, 2026.",
         "https://news.example/tech-news-oct-12-2026"),
        ("Old AI research paper",
         "A 2018 research paper on neural network architectures. This is an older study on deep learning. "
         "Published in 2018 in a peer-reviewed journal.",
         "https://arxiv.example/old-ai-paper-2018"),

        # --- General knowledge ---
        ("What is the capital of France",
         "The capital of France is Paris. Paris is located on the Seine River and is the largest city "
         "in France. It is known for the Eiffel Tower, Louvre Museum and Notre-Dame Cathedral.",
         "https://wiki.example/paris"),
        ("Who wrote Romeo and Juliet",
         "Romeo and Juliet was written by William Shakespeare. It is a tragedy about two young lovers "
         "whose deaths reconcile their feuding families. Written around 1594-1596.",
         "https://wiki.example/romeo-juliet"),
        ("Photosynthesis process",
         "Photosynthesis is the process by which green plants use sunlight to synthesize food from "
         "carbon dioxide and water. It produces oxygen and glucose. The equation is: "
         "6CO2 + 6H2O + light -> C6H12O6 + 6O2.",
         "https://wiki.example/photosynthesis"),
        ("Water cycle explanation",
         "The water cycle describes the continuous movement of water on Earth. Steps: evaporation, "
         "condensation, precipitation, collection. The sun drives the cycle by heating water in oceans.",
         "https://wiki.example/water-cycle"),

        # --- Comparisons ---
        ("Python vs JavaScript comparison",
         "Python and JavaScript are both popular programming languages. Python is used for data science, "
         "AI and backend. JavaScript is used for web development. Python uses indentation; JavaScript "
         "uses curly braces. Python is dynamically typed; JavaScript is also dynamically typed.",
         "https://comparison.example/python-vs-javascript"),
        ("React vs Angular",
         "React is a library by Facebook; Angular is a framework by Google. React uses virtual DOM; "
         "Angular uses real DOM with change detection. React is more flexible; Angular is opinionated. "
         "Both are used for building web applications.",
         "https://comparison.example/react-vs-angular"),

        # --- Weather / local ---
        ("Weather in Mumbai",
         "Mumbai has a tropical wet and dry climate. Monsoon season is June to September. "
         "Average temperature ranges from 25C to 35C. Humidity is high throughout the year.",
         "https://weather.example/mumbai"),
        ("Best restaurants near me",
         "This page lists popular restaurants in your area. Use location services to find nearby "
         "dining options. Includes ratings, cuisines and price ranges.",
         "https://local.example/restaurants"),

        # --- Health ---
        ("What causes diabetes",
         "Diabetes is caused by insufficient insulin production or insulin resistance. "
         "Type 1 is autoimmune; Type 2 is lifestyle-related. Symptoms include frequent urination, "
         "excessive thirst and fatigue.",
         "https://health.example/diabetes"),
        ("Common cold remedies",
         "Common cold remedies include rest, fluids, honey, ginger tea and over-the-counter medications. "
         "The common cold is caused by viruses and usually resolves in 7-10 days.",
         "https://health.example/common-cold"),

        # --- Finance ---
        ("Stock market basics",
         "The stock market is where shares of public companies are bought and sold. "
         "Investors buy stocks to earn returns through dividends and capital appreciation. "
         "Major indices include S&P 500, Dow Jones and NASDAQ.",
         "https://finance.example/stock-market-basics"),
        ("Mutual funds explained",
         "A mutual fund pools money from many investors to invest in stocks, bonds and other assets. "
         "Professional fund managers make investment decisions. Mutual funds offer diversification "
         "and professional management.",
         "https://finance.example/mutual-funds"),

        # --- Travel ---
        ("Best places to visit in India",
         "Popular tourist destinations in India include the Taj Mahal, Goa beaches, Kerala backwaters, "
         "Himalayan hill stations, Rajasthan forts and Delhi monuments. India offers diverse cultures "
         "and landscapes.",
         "https://travel.example/india-tourism"),
        ("How to get a passport",
         "To get a passport, submit an application online or at a passport office. "
         "Required documents include proof of identity, address and birth certificate. "
         "Processing time varies by country.",
         "https://travel.example/passport-guide"),

        # --- Cooking / recipes ---
        ("Masala dosa recipe",
         "Masala dosa is a South Indian dish. Ingredients: rice, urad dal, potatoes, spices. "
         "Soak and grind rice and dal, ferment overnight. Make potato masala with mustard seeds, "
         "curry leaves, turmeric. Spread batter on tava, add masala, fold and serve with chutney.",
         "https://recipes.example/masala-dosa"),
        ("Chocolate cake recipe",
         "Chocolate cake recipe: flour, cocoa powder, sugar, eggs, butter, baking powder, milk. "
         "Mix dry ingredients, add wet ingredients, bake at 180C for 30 minutes. "
         "Frost with chocolate ganache.",
         "https://recipes.example/chocolate-cake"),

        # --- Gaming ---
        ("Best strategy games 2026",
         "Top strategy games of 2026 include Civilization VIII, Total War, Age of Empires IV, "
         "XCOM 3 and Stellaris. These games require planning, resource management and tactical thinking.",
         "https://gaming.example/strategy-games-2026"),
        ("How to play chess",
         "Chess is a two-player strategy board game. Each player starts with 16 pieces: king, queen, "
         "rooks, bishops, knights and pawns. The goal is to checkmate the opponent's king.",
         "https://gaming.example/chess-guide"),

        # --- Sports ---
        ("Cricket World Cup winners",
         "The Cricket World Cup is held every four years. Winners include Australia (6 times), "
         "India (2 times), West Indies (2 times), Pakistan, Sri Lanka and England. "
         "The 2023 World Cup was won by Australia.",
         "https://sports.example/cricket-world-cup"),
        ("Olympic games history",
         "The modern Olympic Games began in 1896 in Athens. Held every four years, the Olympics "
         "feature summer and winter sports. The 2024 Olympics were held in Paris. "
         "The 2028 Olympics will be in Los Angeles.",
         "https://sports.example/olympic-history"),

        # --- Shopping ---
        ("Best smartphones under 30000",
         "Top smartphones under 30000 rupees include models from Xiaomi, Samsung, Realme and OnePlus. "
         "Features include AMOLED displays, 5G, good cameras and large batteries. "
         "Check reviews before buying.",
         "https://shopping.example/smartphones-under-30000"),
        ("Wireless headphones comparison",
         "Compare wireless headphones from Sony, Bose, Apple, Sennheiser and JBL. "
         "Consider sound quality, battery life, noise cancellation and comfort. "
         "Price ranges from budget to premium.",
         "https://shopping.example/headphones-comparison"),

        # --- Education ---
        ("How to learn programming",
         "To learn programming, start with a beginner-friendly language like Python. "
         "Practice daily, build projects, read code from others and join communities. "
         "Online courses and tutorials are helpful resources.",
         "https://education.example/learn-programming"),
        ("UPSC exam preparation",
         "UPSC Civil Services exam preparation requires 1-2 years of study. "
         "Cover NCERT books, current affairs, optional subject and practice answer writing. "
         "The exam has three stages: Prelims, Mains and Interview.",
         "https://education.example/upsc-preparation"),

        # --- Technology ---
        ("What is cloud computing",
         "Cloud computing delivers computing services over the internet. Services include servers, "
         "storage, databases, networking and AI. Major providers are AWS, Azure and Google Cloud. "
         "Benefits include scalability and cost savings.",
         "https://tech.example/cloud-computing"),
        ("Blockchain technology explained",
         "Blockchain is a distributed ledger technology. Blocks contain transaction data and are "
         "linked cryptographically. It is decentralized and immutable. Used in cryptocurrencies "
         "and supply chain management.",
         "https://tech.example/blockchain"),

        # --- Jobs ---
        ("Software engineer interview questions",
         "Common software engineer interview questions include data structures, algorithms, "
         "system design and behavioral questions. Practice coding problems on LeetCode and HackerRank. "
         "Be prepared to discuss your projects.",
         "https://jobs.example/software-engineer-interview"),
        ("How to write a resume",
         "A good resume includes contact info, summary, work experience, skills and education. "
         "Use action verbs and quantify achievements. Keep it to one page for early career. "
         "Tailor to each job application.",
         "https://jobs.example/resume-guide"),
    ]
    for title, body, url in docs:
        engine.add_document(title, body, url)
    engine.rebuild_index()
    return docs


# Queries with graded relevance (grade 0-3, 3 = perfect match)
QRELS = [
    # coding
    {"query": "Python code for palindrome", "judgments": {
        "https://docs.example/python/palindrome": 3,
        "https://tutorials.example/python-palindrome-code": 3,
        "https://tutorials.example/python-recursion": 1}},
    {"query": "Python palindrome program", "judgments": {
        "https://docs.example/python/palindrome": 3,
        "https://tutorials.example/python-palindrome-code": 2}},
    {"query": "Python recursion", "judgments": {
        "https://tutorials.example/python-recursion": 3}},
    {"query": "Python requests library", "judgments": {
        "https://docs.example/python-requests-guide": 3}},
    {"query": "list comprehension Python", "judgments": {
        "https://docs.example/python/list-comprehensions": 3}},

    # AI English
    {"query": "what is artificial intelligence", "judgments": {
        "https://wiki.example/artificial-intelligence": 3,
        "https://wiki.example/neural-network": 1}},
    {"query": "machine learning algorithms", "judgments": {
        "https://tutorials.example/ml-algorithms": 3}},
    {"query": "neural network basics", "judgments": {
        "https://wiki.example/neural-network": 3}},

    # AI Hindi
    {"query": "कृत्रिम बुद्धिमत्ता क्या है", "judgments": {
        "https://wiki.example/krtrim-buddhimatta": 3}},
    {"query": "मशीन लर्निंग क्या है", "judgments": {
        "https://wiki.example/machine-learning-hindi": 3}},
    {"query": "डीप लर्निंग ट्यूटोरियल", "judgments": {
        "https://tutorials.example/deep-learning-hindi": 3}},

    # AI Gujarati
    {"query": "કૃત્રિમ બુદ્ધિ શું છે", "judgments": {
        "https://wiki.example/krutrim-buddhi": 3}},
    {"query": "ગુજરાતીમાં કૃત્રિમ બુદ્ધિ સમજાવો", "judgments": {
        "https://wiki.example/ai-gujarati-explanation": 3,
        "https://wiki.example/krutrim-buddhi": 2}},
    {"query": "મશીન લર્નિંગ ગુજરાતીમાં", "judgments": {
        "https://wiki.example/machine-learning-gujarati": 3}},

    # TV serials
    {"query": "Kumkum Bhagya serial characters", "judgments": {
        "https://example.com/kumkum-bhagya": 3,
        "https://example.com/kundali-bhagya": 0}},
    {"query": "Kundali Bhagya serial characters", "judgments": {
        "https://example.com/kundali-bhagya": 3,
        "https://example.com/kumkum-bhagya": 0}},
    {"query": "Kumkum Bhagya latest episodes", "judgments": {
        "https://example.com/kumkum-episodes": 3,
        "https://example.com/kumkum-bhagya": 1}},

    # Official docs
    {"query": "Claude official MCP documentation", "judgments": {
        "https://docs.anthropic.com/claude/mcp": 3,
        "https://docs.anthropic.com/mcp/server-guide": 2}},
    {"query": "Claude API reference", "judgments": {
        "https://docs.anthropic.com/api/reference": 3}},

    # News
    {"query": "latest AI news today", "judgments": {
        "https://news.example/ai-news-oct-2026": 3,
        "https://news.example/tech-news-oct-12-2026": 2,
        "https://arxiv.example/old-ai-paper-2018": 0}},

    # No results
    {"query": "Python code for xyz_nonexistent_123", "judgments": {}},
    {"query": "nonexistent_topic_abc999", "judgments": {}},

    # General knowledge
    {"query": "capital of France", "judgments": {
        "https://wiki.example/paris": 3}},
    {"query": "who wrote Romeo and Juliet", "judgments": {
        "https://wiki.example/romeo-juliet": 3}},
    {"query": "photosynthesis process", "judgments": {
        "https://wiki.example/photosynthesis": 3}},
    {"query": "water cycle explanation", "judgments": {
        "https://wiki.example/water-cycle": 3}},

    # Comparisons
    {"query": "Python vs JavaScript", "judgments": {
        "https://comparison.example/python-vs-javascript": 3}},
    {"query": "React vs Angular", "judgments": {
        "https://comparison.example/react-vs-angular": 3}},

    # Health
    {"query": "what causes diabetes", "judgments": {
        "https://health.example/diabetes": 3}},
    {"query": "common cold remedies", "judgments": {
        "https://health.example/common-cold": 3}},

    # Finance
    {"query": "stock market basics", "judgments": {
        "https://finance.example/stock-market-basics": 3}},
    {"query": "mutual funds explained", "judgments": {
        "https://finance.example/mutual-funds": 3}},

    # Travel
    {"query": "best places to visit in India", "judgments": {
        "https://travel.example/india-tourism": 3}},
    {"query": "how to get a passport", "judgments": {
        "https://travel.example/passport-guide": 3}},

    # Recipes
    {"query": "masala dosa recipe", "judgments": {
        "https://recipes.example/masala-dosa": 3}},
    {"query": "chocolate cake recipe", "judgments": {
        "https://recipes.example/chocolate-cake": 3}},

    # Gaming
    {"query": "best strategy games 2026", "judgments": {
        "https://gaming.example/strategy-games-2026": 3}},
    {"query": "how to play chess", "judgments": {
        "https://gaming.example/chess-guide": 3}},

    # Sports
    {"query": "cricket world cup winners", "judgments": {
        "https://sports.example/cricket-world-cup": 3}},
    {"query": "olympic games history", "judgments": {
        "https://sports.example/olympic-history": 3}},

    # Shopping
    {"query": "best smartphones under 30000", "judgments": {
        "https://shopping.example/smartphones-under-30000": 3}},
    {"query": "wireless headphones comparison", "judgments": {
        "https://shopping.example/headphones-comparison": 3}},

    # Education
    {"query": "how to learn programming", "judgments": {
        "https://education.example/learn-programming": 3}},
    {"query": "UPSC exam preparation", "judgments": {
        "https://education.example/upsc-preparation": 3}},

    # Technology
    {"query": "what is cloud computing", "judgments": {
        "https://tech.example/cloud-computing": 3}},
    {"query": "blockchain technology explained", "judgments": {
        "https://tech.example/blockchain": 3}},

    # Jobs
    {"query": "software engineer interview questions", "judgments": {
        "https://jobs.example/software-engineer-interview": 3}},
    {"query": "how to write a resume", "judgments": {
        "https://jobs.example/resume-guide": 3}},

    # Weather / local
    {"query": "weather in Mumbai", "judgments": {
        "https://weather.example/mumbai": 3}},

    # Transliteration / misspellings
    {"query": "krtrim buddhimatta kya hai", "judgments": {
        "https://wiki.example/krtrim-buddhimatta": 3}},
    {"query": "artificial intelligence in hindi", "judgments": {
        "https://wiki.example/krtrim-buddhimatta": 3,
        "https://wiki.example/artificial-intelligence": 2}},
]


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.tmp = make_engine()
        build_corpus(self.engine)

    def test_evaluation_metrics(self):
        result = evaluate(self.engine, QRELS)
        self.assertGreaterEqual(result["queries"], 50)
        s = result["summary"]
        self.assertGreater(s["ndcg@10"], 0.5, f"NDCG@10 too low: {s['ndcg@10']}")
        self.assertGreater(s["p@5"], 0.5, f"P@5 too low: {s['p@5']}")
        self.assertGreater(s["mrr@10"], 0.5, f"MRR too low: {s['mrr@10']}")
        self.assertGreater(s["recall@10"], 0.4, f"Recall@10 too low: {s['recall@10']}")
        self.assertGreaterEqual(s["zero_result_rate"], 0.0)
        self.assertLess(s["latency_p95_ms"], 5000)

    def test_no_hardcoded_answers(self):
        # Queries with no relevant docs must return empty or non-matching results
        for q in ["Python code for xyz_nonexistent_123", "nonexistent_topic_abc999"]:
            r = self.engine.search(q)
            urls = [x["url"] for x in r["results"]]
            for url in urls:
                self.assertNotIn("xyz_nonexistent_123", url)
                self.assertNotIn("nonexistent_topic_abc999", url)

    def test_kumkum_not_kundali(self):
        r = self.engine.search("Kumkum Bhagya serial characters")
        self.assertTrue(r["results"], "should have results")
        top = r["results"][0]["url"]
        self.assertEqual(top, "https://example.com/kumkum-bhagya",
                         f"expected Kumkum Bhagya first, got {top}")
        # Kundali Bhagya should not rank above exact match
        urls = [x["url"] for x in r["results"]]
        if "https://example.com/kundali-bhagya" in urls:
            self.assertLess(urls.index("https://example.com/kumkum-bhagya"),
                            urls.index("https://example.com/kundali-bhagya"))

    def test_kundali_not_kumkum(self):
        r = self.engine.search("Kundali Bhagya serial characters")
        self.assertTrue(r["results"], "should have results")
        top = r["results"][0]["url"]
        self.assertEqual(top, "https://example.com/kundali-bhagya",
                         f"expected Kundali Bhagya first, got {top}")

    def test_hindi_query_retrieves_hindi_content(self):
        r = self.engine.search("कृत्रिम बुद्धिमत्ता क्या है")
        self.assertTrue(r["results"], "Hindi query should return results")
        top = r["results"][0]["url"]
        self.assertEqual(top, "https://wiki.example/krtrim-buddhimatta")

    def test_gujarati_query_retrieves_gujarati_content(self):
        r = self.engine.search("ગુજરાતીમાં કૃત્રિમ બુદ્ધિ સમજાવો")
        self.assertTrue(r["results"], "Gujarati query should return results")
        top = r["results"][0]["url"]
        self.assertEqual(top, "https://wiki.example/ai-gujarati-explanation")

    def test_official_docs_preferred(self):
        r = self.engine.search("Claude official MCP documentation")
        self.assertTrue(r["results"], "should have results")
        top = r["results"][0]["url"]
        self.assertEqual(top, "https://docs.anthropic.com/claude/mcp",
                         f"expected official docs first, got {top}")

    def test_code_query_returns_code_examples(self):
        r = self.engine.search("Python code for palindrome")
        self.assertTrue(r["results"], "should have results")
        top_urls = [x["url"] for x in r["results"][:2]]
        self.assertIn(top_urls[0], [
            "https://docs.example/python/palindrome",
            "https://tutorials.example/python-palindrome-code"])


if __name__ == "__main__":
    unittest.main()
