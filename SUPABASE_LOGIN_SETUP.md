# Google Login via Supabase — setup guide

Honest note first: I wrote this as a guide rather than shipping the code,
because OAuth is the one thing you can't test without live credentials.
Half-tested auth that silently fails is worse than no auth. Follow this and
it'll work; ping me with any error and I'll fix the specific step.

## 1. Make a Supabase project
1. supabase.com → sign in → **New Project**
2. Name it (e.g. `jarvis`), set a database password, pick the region closest
   to you (Mumbai/Singapore for India)
3. Wait ~2 minutes for it to provision
4. **Settings → API** — copy these two, you'll need them:
   - Project URL (`https://xxxxx.supabase.co`)
   - `anon` `public` key

## 2. Get Google OAuth credentials
1. console.cloud.google.com → new project
2. **APIs & Services → OAuth consent screen**
   - User type: External → Create
   - Fill app name, your email, save through the steps
   - Add yourself under **Test users** (otherwise you'll get "app not verified")
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Application type: **Web application**
   - Under **Authorized redirect URIs**, add exactly:
     ```
     https://xxxxx.supabase.co/auth/v1/callback
     ```
     (your Supabase project URL + `/auth/v1/callback`)
4. Copy the **Client ID** and **Client Secret**

## 3. Connect them
In Supabase: **Authentication → Providers → Google**
- Toggle it on
- Paste the Client ID and Client Secret
- Save

Then **Authentication → URL Configuration**:
- Site URL: `http://127.0.0.1:8731`
- Additional Redirect URLs: `http://127.0.0.1:8731`

That last step is the one people miss — without it Google logs you in and
then bounces you nowhere.

## 4. Wire it into Jarvis

Install the client:
```
pip install supabase
```

Add to `config.py`:
```python
SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_ANON_KEY = "your-anon-key"
LOGIN_REQUIRED = True
```

Add to `server.py`:
```python
from supabase import create_client

_sb = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)

@app.route("/api/login_url")
def api_login_url():
    res = _sb.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {"redirect_to": f"http://127.0.0.1:{config.SERVER_PORT}"},
    })
    return jsonify({"url": res.url})

@app.route("/api/session", methods=["POST"])
def api_session():
    body = request.get_json(force=True, silent=True) or {}
    token = body.get("access_token", "")
    try:
        user = _sb.auth.get_user(token)
        data = memory.load()
        data["user_email"] = user.user.email
        memory.save(data)
        return jsonify({"ok": True, "email": user.user.email})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 401
```

In `index.html`, Supabase returns the token in the URL fragment after
redirect, so read it on load:
```javascript
var hash = window.location.hash;
if (hash.indexOf("access_token") !== -1){
  var token = new URLSearchParams(hash.slice(1)).get("access_token");
  fetch("/api/session", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ access_token: token })
  }).then(function(){ window.location.hash = ""; location.reload(); });
}
```

And a login button that calls `/api/login_url` then
`window.location = data.url`.

## 5. Syncing settings across PCs (the actually useful part)
Once login works, this is what makes it worth having. In Supabase → **SQL
Editor**, run:

```sql
create table jarvis_settings (
  user_id uuid references auth.users primary key,
  settings jsonb,
  updated_at timestamptz default now()
);

alter table jarvis_settings enable row level security;

create policy "own settings" on jarvis_settings
  for all using (auth.uid() = user_id);
```

That RLS policy matters — without it, any logged-in user could read
everyone's rows. With it, each account only ever sees its own.

Then push `memory.load()` up on change and pull it down on login, and your
theme/name/facts follow you between machines.

## Common failure points
- **"redirect_uri_mismatch"** → the URI in Google Console doesn't exactly
  match your Supabase callback URL. Check for a trailing slash.
- **Logs in, lands on a blank page** → Site URL / Redirect URLs not set in
  Supabase step 3.
- **"App not verified"** → add your email under Test users in the OAuth
  consent screen.
