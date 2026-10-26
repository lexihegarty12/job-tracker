# JobTracker

JobTracker is a local job and internship tracker for graduate students.

## Run it

```bash
python3 -m pip install -r requirements.txt
streamlit run app.py
```

The app stores entries in `data/job_tracker.db` and includes demo data on first launch. Delete that database if you want to start with a blank tracker.

## Core experience

- **Today:** next actions due this week, interview count, and pipeline totals.
- **Add job:** paste a posting URL to import available structured fields, then review before saving.
- **Job spreadsheet:** search and filter the full tracker, with the original posting and job description close at hand.
- **Application statuses:** a visual pipeline board for Saved, Applied / Waiting for update, Interviewing, and Offer.
- **Career Services fields:** source, network contact, resume and cover letter versions, interview dates, thank-you notes, and follow-up dates.
- **Local-first:** data and uploaded documents stay in the project’s `data/` directory.

