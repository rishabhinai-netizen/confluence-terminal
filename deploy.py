"""
Confluence Terminal — one-shot GitHub Pages deployment.

Run from inside the automation/ folder:
    pip install requests pynacl
    python deploy.py

You'll be prompted for:
  1. Your GitHub Personal Access Token (starts with ghp_)
  2. Path to your 'Session Cookies' file (Enter to skip)

The script creates a private repo, pushes the code, sets the two cookie secrets,
enables GitHub Pages, triggers the first workflow run, and prints your live URL.
Nothing is written to disk — the PAT and cookies stay only in memory for the run.
"""
from __future__ import annotations
import subprocess, sys, os, re, getpass, json, base64
from pathlib import Path

REPO_NAME = 'confluence-terminal'
REPO_DESC = 'Cross-source equity intelligence terminal'


def require(pkg: str, imp: str = None):
    imp = imp or pkg
    try: __import__(imp)
    except ImportError:
        print(f"Installing {pkg}...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', pkg])
        __import__(imp)


require('requests')
require('pynacl', 'nacl')
import requests
from nacl import encoding, public


def api(method, path, token, **kw):
    r = requests.request(method, f'https://api.github.com{path}',
                         headers={'Authorization': f'Bearer {token}',
                                  'Accept': 'application/vnd.github+json',
                                  'X-GitHub-Api-Version': '2022-11-28'},
                         timeout=30, **kw)
    return r


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(secret_value.encode())
    return base64.b64encode(sealed).decode()


def parse_cookies(cookie_file: Path):
    """Extract SS + ES cookie header lines from the sensitive file."""
    txt = cookie_file.read_text(encoding='utf-8', errors='replace')
    ss = re.search(r'STOCKSCANS\.IN.*?\n\s*\n(_ga=.+?)\n', txt, re.S)
    es = re.search(r'EQUISENSE\.AI.*?\n\s*\n(es_anon_id=.+?)\n', txt, re.S)
    return (ss.group(1).strip() if ss else None,
            es.group(1).strip() if es else None)


def run(*cmd, check=True, capture=False):
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, check=check, capture_output=capture, text=True)
    return r


def main():
    print("\n=== Confluence Terminal · GitHub Pages deployment ===\n")
    token = getpass.getpass("Paste your GitHub PAT (starts with ghp_): ").strip()
    if not token.startswith('ghp_'):
        print("Not a valid PAT. Aborting.")
        sys.exit(1)

    # 0. Verify auth
    r = api('GET', '/user', token)
    if r.status_code != 200:
        print(f"Auth failed: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    owner = r.json()['login']
    print(f"Authenticated as: {owner}\n")

    # Optional: cookies for daily refresh
    ss_cookie = es_cookie = None
    default_path = Path('..') / 'Session Cookies (SENSITIVE - do not share).txt'
    cookie_input = input(f"Path to cookie file [default: {default_path}, Enter to skip]: ").strip()
    cookie_path = Path(cookie_input) if cookie_input else default_path
    if cookie_path.exists():
        ss_cookie, es_cookie = parse_cookies(cookie_path)
        print(f"  StockScans cookie: {'found' if ss_cookie else 'NOT FOUND'}")
        print(f"  EquiSense cookie:  {'found' if es_cookie else 'NOT FOUND'}\n")
    else:
        print(f"  Skipped — add secrets later at repo Settings\n")

    # 1. Create repo
    print(f"[1/6] Creating private repo '{REPO_NAME}'...")
    r = api('POST', '/user/repos', token, json={
        'name': REPO_NAME, 'private': True, 'auto_init': False,
        'description': REPO_DESC, 'has_issues': False, 'has_wiki': False,
    })
    if r.status_code == 201:
        print(f"  Created: {r.json()['clone_url']}")
    elif r.status_code == 422:
        print("  Already exists — reusing")
    else:
        print(f"  FAILED: {r.status_code} {r.text[:300]}"); sys.exit(1)

    # 2. Git init + push
    print(f"\n[2/6] Pushing code to main...")
    if not Path('.git').exists():
        run('git', 'init', '-b', 'main')
    run('git', 'config', 'user.email', 'confluence@local')
    run('git', 'config', 'user.name', 'confluence')
    run('git', 'add', '-A')
    subprocess.run(['git', 'commit', '-m', 'Initial deploy', '--allow-empty'],
                   check=False, capture_output=True)
    subprocess.run(['git', 'remote', 'remove', 'origin'], check=False, capture_output=True)
    remote_url = f'https://x-access-token:{token}@github.com/{owner}/{REPO_NAME}.git'
    run('git', 'remote', 'add', 'origin', remote_url)
    run('git', 'push', '-u', 'origin', 'main', '--force')
    print("  Pushed")

    # 3. Set secrets
    if ss_cookie or es_cookie:
        print(f"\n[3/6] Setting repo secrets...")
        r = api('GET', f'/repos/{owner}/{REPO_NAME}/actions/secrets/public-key', token)
        pk_info = r.json()
        for name, val in [('STOCKSCANS_COOKIE', ss_cookie), ('EQUISENSE_COOKIE', es_cookie)]:
            if not val: continue
            enc = encrypt_secret(pk_info['key'], val)
            r = api('PUT', f'/repos/{owner}/{REPO_NAME}/actions/secrets/{name}', token,
                    json={'encrypted_value': enc, 'key_id': pk_info['key_id']})
            print(f"  {name}: {'set' if r.status_code < 300 else 'FAILED ' + r.text[:200]}")
    else:
        print(f"\n[3/6] Skipped secrets (no cookie file)")

    # 4. Enable Pages
    print(f"\n[4/6] Enabling GitHub Pages (source = GitHub Actions)...")
    r = api('POST', f'/repos/{owner}/{REPO_NAME}/pages', token,
            json={'build_type': 'workflow'})
    if r.status_code in (201, 204):
        print("  Pages enabled")
    elif r.status_code == 409:
        print("  Already enabled")
    else:
        # Fallback: switch existing Pages to workflow build
        r2 = api('PUT', f'/repos/{owner}/{REPO_NAME}/pages', token,
                 json={'build_type': 'workflow'})
        print(f"  {r2.status_code} {r2.text[:200] if r2.status_code >= 300 else 'switched to workflow build'}")

    # 5. Trigger first workflow run
    print(f"\n[5/6] Triggering first workflow run...")
    r = api('POST', f'/repos/{owner}/{REPO_NAME}/actions/workflows/daily.yml/dispatches',
            token, json={'ref': 'main'})
    if r.status_code == 204:
        print("  Workflow triggered")
    else:
        print(f"  {r.status_code} — workflow will fire on next cron (07:00 IST) if this failed")

    # 6. Done
    print(f"\n[6/6] Done!\n")
    print(f"Repo:      https://github.com/{owner}/{REPO_NAME}")
    print(f"Actions:   https://github.com/{owner}/{REPO_NAME}/actions")
    print(f"Live URL:  https://{owner}.github.io/{REPO_NAME}/")
    print(f"           (goes live in ~2-3 min after workflow completes)")
    print(f"\nBookmark the Live URL. From tomorrow, auto-refreshes daily at 07:00 IST.")


if __name__ == '__main__':
    main()
