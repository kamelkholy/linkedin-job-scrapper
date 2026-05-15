"""Curated default list of remote-friendly companies.

Used to seed the `companies` table on first launch. Users can add or
remove companies from the UI afterwards. Each entry can supply:

    name          — display name (required if slug missing)
    slug          — LinkedIn company slug (e.g. "federato" for
                    https://www.linkedin.com/company/federato/)
    linkedin_url  — optional explicit company URL
"""

from __future__ import annotations

DEFAULT_REMOTE_COMPANIES: list[dict] = [
    {"name": "Kit"},
    {"name": "Zapier"},
    {"name": "beehiiv"},
    {"name": "DuckDuckGo"},
    {"name": "Ghost"},
    {"name": "GitLab"},
    {"name": "Wikimedia Foundation"},
    {"name": "Circle"},
    {"name": "Phantom"},
    {"name": "Buffer"},
    {"name": "Canonical"},
    {"name": "Automattic"},
    {"name": "Supabase"},
    {"name": "Doist"},
    {"name": "SafetyWing"},
    {"name": "Toggl"},
    {"name": "YNAB"},
    {"name": "Contra"},
    {"name": "Superside"},
    {"name": "Atlassian"},
    {"name": "Deel"},
    {"name": "Remote"},
    {"name": "Harvest"},
    {"name": "Prezi"},
    {"name": "Constructor"},
    {"name": "Fingerprint"},
    {"name": "Adapty"},
    {"name": "TestGorilla"},
    {"name": "Hubstaff"},
    {"name": "Oyster"},
    {"name": "Federato", "slug": "federato",
     "linkedin_url": "https://www.linkedin.com/company/federato/"},
    {"name": "Infisical", "slug": "infisical",
     "linkedin_url": "https://www.linkedin.com/company/infisical/"},
    {"name": "Simular AI", "slug": "simular-ai",
     "linkedin_url": "https://www.linkedin.com/company/simular-ai/"},
    {"name": "Smart Bricks", "slug": "smart-bricks",
     "linkedin_url": "https://www.linkedin.com/company/smart-bricks/"},
    {"name": "Railway", "slug": "railwayapp",
     "linkedin_url": "https://www.linkedin.com/company/railwayapp/"},
    {"name": "Block"},
    {"name": "HashiCorp"},
    {"name": "Discord"},
    {"name": "Figma"},
    {"name": "Stripe"},
    {"name": "Altinity"},
    {"name": "Anovium"},
    {"name": "Appsilon"},
    {"name": "Camunda"},
    {"name": "Chess.com"},
    {"name": "Clipboard Health"},
]
