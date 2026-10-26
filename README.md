# JobTracker

JobTracker is a local job and internship tracker for graduate students.

## Run it

```bash
python3 -m pip install -r requirements.txt
streamlit run app.py
```

The app opens with a username/password account screen. Passwords are stored as salted PBKDF2 hashes, and each account sees only its own opportunities.

## Deploy with Streamlit Community Cloud

1. Push this repository to GitHub.
2. In Streamlit Community Cloud, choose **New app** and select `app.py` from this repository.
3. Deploy. The app will create its local SQLite database on first use.

For a production deployment, connect the app to a hosted database and persistent file storage. Streamlit Community Cloud can restart apps, so its local SQLite database and uploaded documents should be treated as demo/local storage.

The app stores entries in `data/job_tracker.db` and includes demo data on first launch. Delete that database if you want to start with a blank tracker.

## Core experience

- **Today:** next actions due this week, interview count, and pipeline totals.
- **Add job:** paste a posting URL to import available structured fields, then review before saving.
- **Job spreadsheet:** search and filter the full tracker, with the original posting and job description close at hand.
- **Application statuses:** a visual pipeline board for Saved, Applied / Waiting for update, Interviewing, and Offer.
- **Career Services fields:** source, network contact, resume and cover letter versions, interview dates, thank-you notes, and follow-up dates.
- **Local-first:** data and uploaded documents stay in the project’s `data/` directory.

