# Using the WhatsMyName JSON Dataset

## What is it?

WhatsMyName maintains a community-curated JSON file (`wmn-data.json`) containing detection rules for hundreds of websites. Each entry tells you:

- The URL pattern for a profile page
- What to look for in the response to determine if an account exists or not

This means you don't need to rely on any external tool — you load the JSON, loop through sites, make HTTP requests, and check the responses yourself.

## Getting the Data

```bash
# clone the repo
git clone https://github.com/WebBreacher/WhatsMyName.git

# the file you care about
cat WhatsMyName/wmn-data.json
```

Or fetch it directly in code:

```python
import requests

url = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
data = requests.get(url).json()
```

## JSON Structure

Each site entry looks roughly like this:

```json
{
  "name": "GitHub",
  "uri_check": "https://github.com/{account}",
  "e_code": 200,
  "e_string": "repositor",
  "m_code": 404,
  "m_string": "Not Found",
  "known": ["johndoe", "janedoe"],
  "cat": "coding",
  "valid": true
}
```

Key fields:

| Field | Meaning |
|---|---|
| `name` | Site name |
| `uri_check` | URL template — `{account}` gets replaced with the username |
| `e_code` | Expected HTTP status code when account **exists** |
| `e_string` | String found in response body when account **exists** |
| `m_code` | Expected HTTP status code when account is **missing** |
| `m_string` | String found in response body when account is **missing** |
| `known` | Known valid usernames for testing |
| `cat` | Category (social, coding, gaming, etc.) |
| `valid` | Whether this entry is currently working |

## Basic Checker

```python
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

def load_sites(path="wmn-data.json"):
    """Load the WhatsMyName JSON database."""
    with open(path) as f:
        data = json.load(f)
    # only use entries marked as valid
    return [site for site in data["sites"] if site.get("valid", True)]

def check_site(site, username):
    """Check if a username exists on a single site."""
    url = site["uri_check"].replace("{account}", username)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)

        # check status code match
        code_match = resp.status_code == site.get("e_code", 200)

        # check if the "exists" string is in the response body
        string_match = True
        if "e_string" in site and site["e_string"]:
            string_match = site["e_string"].lower() in resp.text.lower()

        if code_match and string_match:
            return {
                "site": site["name"],
                "url": url,
                "status": "found",
                "category": site.get("cat", "unknown"),
                "http_code": resp.status_code
            }

    except requests.RequestException:
        return {
            "site": site["name"],
            "url": url,
            "status": "error"
        }

    return None

def check_username(username, sites, max_workers=20):
    """Check a username across all sites using thread pool."""
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(check_site, site, username): site
            for site in sites
        }

        for future in as_completed(futures):
            result = future.result()
            if result and result["status"] == "found":
                results.append(result)
                print(f"  [+] {result['site']}: {result['url']}")

    return results

if __name__ == "__main__":
    username = input("Enter username: ").strip()
    sites = load_sites()
    print(f"Checking {username} across {len(sites)} sites...\n")
    results = check_username(username, sites)
    print(f"\nFound {len(results)} accounts.")
```

## Async Version (faster)

```python
import aiohttp
import asyncio
import json

async def check_site_async(session, site, username):
    """Check a single site asynchronously."""
    url = site["uri_check"].replace("{account}", username)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            status = resp.status
            body = await resp.text()

            code_match = status == site.get("e_code", 200)
            string_match = True

            if "e_string" in site and site["e_string"]:
                string_match = site["e_string"].lower() in body.lower()

            if code_match and string_match:
                return {
                    "site": site["name"],
                    "url": url,
                    "status": "found",
                    "category": site.get("cat", "unknown")
                }

    except Exception:
        pass

    return None

async def check_username_async(username, sites, concurrency=30):
    """Run all checks with a concurrency limit."""
    semaphore = asyncio.Semaphore(concurrency)
    results = []

    async def sem_check(site):
        async with semaphore:
            return await check_site_async(session, site, username)

    async with aiohttp.ClientSession() as session:
        tasks = [sem_check(site) for site in sites]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result:
                results.append(result)
                print(f"  [+] {result['site']}: {result['url']}")

    return results

if __name__ == "__main__":
    username = input("Enter username: ").strip()

    with open("wmn-data.json") as f:
        sites = [s for s in json.load(f)["sites"] if s.get("valid", True)]

    print(f"Checking {username} across {len(sites)} sites...\n")
    results = asyncio.run(check_username_async(username, sites))
    print(f"\nFound {len(results)} accounts.")
```

## Reducing False Positives

The basic checker above will give you false positives. Some sites return 200 for everything, some redirect to a generic page, some show a "user not found" message but still return 200. Ways to handle this:

### 1. Use the miss string too

```python
# if the "missing" string IS found, account doesn't exist
# even if the status code looks like it does
if "m_string" in site and site["m_string"]:
    if site["m_string"].lower() in body.lower():
        return None  # false positive, account doesn't actually exist
```

### 2. Check response length

Some sites return a short generic page for missing users. Compare against a baseline:

```python
# request a username that definitely doesn't exist
baseline_url = site["uri_check"].replace("{account}", "asdkjh3k4jh5xzz99")
baseline_resp = requests.get(baseline_url, headers=headers, timeout=10)
baseline_length = len(baseline_resp.text)

# if the real response is similar length to the 404 baseline, it's probably a false positive
if abs(len(resp.text) - baseline_length) < 100:
    return None
```

### 3. Check for redirects

```python
# some sites redirect non-existent users to a homepage or signup page
resp = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
if resp.status_code in (301, 302, 303, 307, 308):
    return None  # redirected, account probably doesn't exist
```

## Filtering by Category

The JSON includes categories so you can target specific types of sites:

```python
# only check coding platforms
coding_sites = [s for s in sites if s.get("cat") == "coding"]

# only check social media
social_sites = [s for s in sites if s.get("cat") == "social"]

# available categories (varies but typically):
# social, coding, gaming, dating, finance, news, shopping,
# music, video, photography, art, business, education, etc.

categories = set(s.get("cat", "unknown") for s in sites)
print(f"Available categories: {categories}")
```

## Adding Your Own Sites

If you find a site that WhatsMyName doesn't cover, add your own entries:

```python
custom_sites = [
    {
        "name": "CustomSite",
        "uri_check": "https://customsite.com/user/{account}",
        "e_code": 200,
        "e_string": "profile",
        "m_code": 404,
        "m_string": "not found",
        "cat": "social",
        "valid": True
    }
]

# merge with the official dataset
all_sites = sites + custom_sites
```

To figure out the detection rules for a new site:

```bash
# 1. visit a known existing profile, note the status code and a unique string
curl -s -o /dev/null -w "%{http_code}" https://example.com/user/known_user
curl -s https://example.com/user/known_user | grep -i "profile\|member\|joined"

# 2. visit a non-existent profile, note the status code and error string
curl -s -o /dev/null -w "%{http_code}" https://example.com/user/zzznotarealuser999
curl -s https://example.com/user/zzznotarealuser999 | grep -i "not found\|404\|doesn't exist"

# 3. use those values for e_code, e_string, m_code, m_string
```

