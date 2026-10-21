# Running Independent

Start `./run.sh` for a localhost server. Customize `sources.txt` and the documented
`OWNSEARCH_*` settings. Do not reuse an old running server from the `dependent`
branch: `/health` must report `mode: independent` and `database: false`.

For remote access, use `serve --require-auth`, local API keys, HTTPS through your
own reverse proxy and machine-appropriate concurrency budgets. Website robots,
access denials and Retry-After are respected. There is no persistent document
index, automatic full-web crawling, provider account or paid API.

Memory caches disappear on restart. Refer to docs/PROGRESS.md for measured limits.
