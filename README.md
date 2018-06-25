# SpotBot Playlister

A scraper to automatically find the top songs posted to a music subreddit every
day, keeping you up to date on the best new music.

## Preparation:

First, set up your local environment.

```
cd spotbot-playlister
virtualenv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

You'll need to authenticate your Spotify and Reddit accounts for use. Change the
following variables in `spotbot_playlister.py` to match what was provided by the
respective developer pages.
* `REDDIT_CLIENT_ID`
* `REDDIT_CLIENT_SECRET`
* `REDDIT_USER_AGENT` - created by you (e.g. `web:com.test.spotbot:v0.0.1`)
* `SPOTIFY_CLIENT_ID`
* `SPOTIFY_CLIENT_SECRET`
* `SPOTIFY_USER_ID` - the user id of the spotify user making requests. This can
  be found at https://www.spotify.com/us/account/overview/

You'll also need to authenticate your Spotify account through an actual web
browser. Run the program through the instructions below, then copy the URL from
your browser back to the prompt on the terminal when asked (the authenctication
key will be stored on the local filesystem at `.cache-<SPOTIFY_USER_ID>`).

## Usage

To run a basic run on a single subreddit for one day's worth of songs:
```bash
./spotbot_playlister.py --subreddit popheads --daily
```

Create a new playlist with the top 50 songs from a subreddit's recent history:
```bash
./spotbot_playlister.py --subreddit hiphopheads --new-list --playlist-length 50
```

Update a playlist with the top 20 songs over the past week, but with throttling:
```bash
./spotbot_playlister.py --subreddit listentothis --weekly --num-songs 20 --max-spotify-qps 5
```

There are also 3 helper scripts available:
```bash
# Run the daily update of the playlists for every subreddit defined in music_subreddits.txt
./run_daily.sh

# Create brand new playlists for every music subreddit with recent songs
./run_new_lists.sh

# Sort every known music subreddit on reddit by genre and number of subscribers:
#   Mostly helpful for picking which subreddits you care about in 'music_subreddits'
./subreddit_counts.py
```