# Commands

```bash

# Run one batch using the active ScrapeConfig
uv run python manage.py scrape_jobs

# Create a new config starting at ID 4056789 and run one batch
uv run python manage.py scrape_jobs --start 4056789

# Override batch size to 100 for this run
uv run python manage.py scrape_jobs --batch 100

# Run indefinitely, batch after batch
uv run python manage.py scrape_jobs --continuous

# Run indefinitely with a 10s pause between batches
uv run python manage.py scrape_jobs --continuous --pause 10

```
