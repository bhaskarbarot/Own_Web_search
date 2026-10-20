# Install profiles, models and source records

The base profile was tested with Python 3.12 and the versions below. Core search also retains a standard-library fallback. `sh scripts/setup.sh base` creates `.venv`, installs the base profile and runs the regression suite. The `full` profile installs optional runtimes; model weights and language packs are separate local artifacts. No model is downloaded by a search request.

| Component | Version tested | License evidence | Source |
| --- | --- | --- | --- |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python, installed package metadata | [PyPI](https://pypi.org/project/regex/) |
| stopwordsiso | 0.7.1 | MIT, installed package metadata | [PyPI](https://pypi.org/project/stopwordsiso/) |
| dateparser | 1.4.3 | BSD-3-Clause, installed package metadata | [Documentation](https://dateparser.readthedocs.io/en/latest/) |
| holidays | 0.107 | MIT, installed package metadata | [Documentation](https://holidays.readthedocs.io/en/dev/api/) |
| charset-normalizer | 3.5.2 | MIT, installed package metadata | [PyPI](https://pypi.org/project/charset-normalizer/) |
| multilingual-e5-small weights | Not installed or executed | MIT on primary model card | [Model card](https://huggingface.co/intfloat/multilingual-e5-small) |
| ONNX Runtime / sentence-transformers / FAISS / Lingua runtime artifacts | Not installed or executed | UNVERIFIED for the exact eventual versions | [Sentence Transformers](https://www.sbert.net/docs/package_reference/cross_encoder/model.html), [Lingua](https://github.com/pemistahl/lingua-py) |
| Chosen reranker / spaCy model weights | Not installed or selected | UNVERIFIED | Supply the local artifact and its primary license record |
| Argos library | Not installed | MIT or CC0 according to primary repository; installed version unverified | [Repository](https://github.com/argosopentech/argos-translate) |
| Argos language packs | Not installed or selected | UNVERIFIED per pack; library license does not certify model/data rights | Check each pack before claiming coverage |
| ai4bharat-transliteration | Dependency-resolution dry run only | UNVERIFIED for the selected model/runtime artifacts | Actual execution not tested; heavy GPU dependencies excluded from default profiles |
| MIRACL topic/qrel files | en/hi dev files downloaded and checksummed | Apache-2.0 on primary dataset card | [Dataset](https://huggingface.co/datasets/miracl/miracl) |
| MIRACL Wikipedia passages | Not downloaded | Follow the corpus' attribution and underlying Wikipedia text rights | [Primary project](https://github.com/project-miracl/miracl) |
| IndicIRSuite | Not downloaded or executed | Repository MIT; actual downloaded data/license artifacts remain UNVERIFIED | [Repository](https://github.com/saifulhaq95/IndicIRSuite), [dataset](https://huggingface.co/datasets/saifulhaq9/indicmarco) |

The existing custom 64-bit simhash implementation is retained rather than introducing a redundant mandatory library. Hindi/Gujarati stopword files and the temporal/output grammar resources remain active fallbacks. Stopwordsiso supplies both Hindi and Gujarati in the tested version; a package install does not establish search-language accuracy.

Configuration uses `data/ownsearch.json` or `OWNSEARCH_<FIELD>` environment variables. Relevant fields:

```json
{
  "remote_knowledge_enabled": false,
  "discovery_mode": "background",
  "discovery_timeout": 8,
  "discovery_provider_timeout": 3,
  "timezone": "UTC",
  "holiday_country": "",
  "searxng_url": "",
  "vector_index": false,
  "embedding_model_path": "",
  "intent_embedding_enabled": false,
  "reranker_enabled": false,
  "reranker_model_path": "",
  "rerank_budget_ms": 40,
  "translation_enabled": false,
  "translation_target": "en",
  "ner_model_path": "",
  "language_detector": "script",
  "document_languages": "en,hi,gu"
}
```

`package_lookup_url` defaults to the public package-metadata API; set it to `""` to disable. The API schema is documented by [PyPI](https://docs.pypi.org/api/json/). The provider reads maintainer-declared documentation/homepage links and validates retrieved content; it never constructs a documentation host from a query. Market source templates and feed files remain independently configurable.

For local labels: `python3 main.py entities-import export.jsonl --limit 10000`. The stream accepts multilingual Wikidata labels/aliases and optional source-enriched `entity_type` values. Without type metadata the placeholder remains `__ENTITY__`; the engine does not invent PERSON/COMPANY identity. Existing public cached records migrate into the local label store. Remote Wikimedia calls require opt-in.

For English intent calibration: `python3 scripts/calibrate_intent.py heldout.tsv --output /tmp/intent_margins.json`. This reports calibration-sample uncertainty, not independent test accuracy. Activate a table in the chosen data directory only after a disjoint validation run. Non-English base classification is general. The optional multilingual adapter also requires a language-specific margin table; absence keeps the core fallback.

For vectors: `python3 main.py vectors-build --model-path /path/to/local-e5 --margins /path/to/semantic-margins.json`. Local ONNX model files are required. The adapter uses `query: ` / `passage: ` prefixes and checks the model artifact hash and index generation. Quantized model preparation/execution was not verified in this session. Semantic margin calibration is separate from naive-Bayes probability calibration; do not reuse the same numeric thresholds across models.

All heavy adapters are disabled until separately configured and evaluated. Missing packages, weights, stale vectors, absent margins and exhausted budgets leave the base results available and report the provider failure/status. A model loader may continue in a bounded daemon worker after the response budget; a timeout is not reported as successful cancellation.
