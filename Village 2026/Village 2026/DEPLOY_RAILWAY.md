# Village 2026 - Railway deploy

## What this app needs

- A Railway web service running `python server.py`
- Railway will build the app from the included `Dockerfile`
- A Railway volume mounted at `/app/data`
- Environment variables for admin login and mail
- Cloudflare DNS pointing `villagecarevent.com` and `www.villagecarevent.com` to Railway

## Railway variables

Set these in Railway under the service's Variables tab:

```text
ADMIN_USER=VillageAdmin
ADMIN_PASSWORD=Village2026!?
SMTP_HOST=your-smtp-host
SMTP_PORT=587
SMTP_USER=your-smtp-username
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=Village Car Event <noreply@villagecarevent.com>
```

`PORT` is provided by Railway automatically.

Do not put these values in the public code if you change them later. Keep them in Railway Variables.

## Persistent uploads and database

Create a Railway volume and attach it to the web service.

Mount path:

```text
/app/data
```

The app stores:

- SQLite database: `/app/data/registrations.sqlite3`
- Uploads: `/app/data/uploads`
- Local mail fallback log: `/app/data/mail.log`

## Domain

After deployment, add the custom domains in Railway:

- `villagecarevent.com`
- `www.villagecarevent.com`

Railway will show the DNS records Cloudflare needs. Add those in Cloudflare DNS.

## Step-by-step

1. Create a GitHub repository for this folder.
2. Push these files to GitHub.
3. Go to Railway and click `New Project`.
4. Choose `Deploy from GitHub repo`.
5. Select the Village 2026 repository.
6. Wait until Railway deploys the service.
7. Open the Railway service and go to `Variables`.
8. Add the admin and SMTP variables listed above.
9. Add a volume to the service.
10. Set the volume mount path to `/app/data`.
11. Redeploy the service.
12. Open the Railway generated domain and check:
    - `/`
    - `/register`
    - `/admin`
    - `/healthz`
13. In Railway, add custom domains:
    - `villagecarevent.com`
    - `www.villagecarevent.com`
14. Copy the DNS records Railway gives you.
15. In Cloudflare DNS, add/update those records.

If Railway shows `Deployment failed during build process`, open `View logs`.
This project includes a `Dockerfile`, so Railway should build it as a Docker app.
Make sure the uploaded repository includes:

- `Dockerfile`
- `server.py`
- `index.html`
- `style.css`
- `script.js`

## Cloudflare notes

- Keep mail records from Zoho as they are.
- Only change web records for `@` and `www`.
- For `www`, use the Railway target shown in Railway.
- For root/apex `villagecarevent.com`, use the exact record Railway gives you.
- Leave Proxy enabled only if Railway's domain setup accepts it. If SSL validation fails, temporarily set it to DNS only until Railway verifies the domain.

## Admin URL

The admin URL is intentionally not linked on the public site:

```text
https://villagecarevent.com/admin
```

Current default login:

```text
VillageAdmin
Village2026!?
```

For production, set the same values or stronger values in Railway Variables.
