#!/usr/bin/env bash

trap "exit" INT
cd $(dirname "$0")
source .venv/bin/activate

LOGFILE="logs/newlist_$(date '+%y%m%d').log"
SUBREDDIT_LIST_FILE='music_subreddits.txt'
PLAYLIST_LENGTH=40
SPOTIFY_QPS=10

SUCCESS_COUNT=0
FAILED_COUNT=0
FAILED_SUBREDDITS=()

mkdir -p logs
while read SUBREDDIT; do
    echo
    echo "Running spotbot to create new playlist for subreddit '$SUBREDDIT'"
    CMD="./spotbot_playlister.py --subreddit $SUBREDDIT --new-list --playlist-length $PLAYLIST_LENGTH --max-spotify-qps $SPOTIFY_QPS --logfile $LOGFILE"
    echo "  $CMD"
    $CMD
    RESULT=$?
        if [ $RESULT -eq 0 ]; then
            SUCCESS_COUNT=$[SUCCESS_COUNT + 1]
        else
            FAILED_COUNT=$[FAILED_COUNT + 1]
            FAILED_SUBREDDITS+=($SUBREDDIT)
        fi
done <$SUBREDDIT_LIST_FILE

echo
echo "Complete! New list subreddit stats: $SUCCESS_COUNT successes, $FAILED_COUNT failures."
if [ -n "$FAILED_SUBREDDITS" ]; then
    echo "  Failed subreddits: ${FAILED_SUBREDDITS[*]}"
fi
