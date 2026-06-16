# Workspace Agent UI

Simple Next.js UI for Supabase login, Google source connection, upload, sync,
chat, and clickable references.

## Setup

Create `frontend/.env.local`:

```bash
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

For Vercel, set `NEXT_PUBLIC_BACKEND_URL` to the Railway backend URL, for
example `https://your-backend.up.railway.app`. Do not set it to the Vercel
frontend URL, or backend calls such as `/setup/status` will return the Next.js
404 page.

In Supabase Auth, enable at least one login provider:

- Email provider for magic-link login
- Google provider for Google login

For Google login, go to:

```text
Supabase Dashboard -> Authentication -> Providers -> Google -> Enable
```

Add your Google OAuth Client ID and Client Secret there. If Google is not
enabled, Supabase returns `Unsupported provider: provider is not enabled`.

Run:

```bash
npm i
npm run dev
```

Open:

```text
http://localhost:3000
```

## Flow

1. User signs in with Supabase Google Auth.
2. Dashboard uses the Supabase user id for backend requests.
3. Connect Drive/Docs/Sheets and Gmail from the source cards.
4. The backend passes `login_hint` to Google OAuth, so if the user is already
   logged into that Google account, Google should skip account login and only
   ask for missing data-access consent.
5. Upload, sync, and ask questions.
6. Agent answers include clickable references.
