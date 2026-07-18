# Commands

```bash

# Run one batch, resuming from MAX(Job.linkedin_id) + 1
uv run python manage.py scrape_jobs

# Start from a specific job ID instead of resuming
uv run python manage.py scrape_jobs --start 4056789

# Override how many IDs to probe this run
uv run python manage.py scrape_jobs --batch 100

# Run indefinitely until interrupted (Ctrl+C)
uv run python manage.py scrape_jobs --continuous

```
