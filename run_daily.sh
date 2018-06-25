#!/usr/bin/env bash

trap "exit" INT

SUBREDDIT_LIST_FILE='music_subreddits.txt'
SONGS_PER_DAY=2
PLAYLIST_LENGTH=40
SPOTIFY_QPS=10

SUCCESS_COUNT=0
FAILED_COUNT=0
FAILED_SUBREDDITS=()

while read SUBREDDIT; do
    echo
    echo "Running spotbot daily song collection for subreddit '$SUBREDDIT'"
    CMD="./spotbot_playlister.py --subreddit $SUBREDDIT --daily --playlist-length $PLAYLIST_LENGTH --num-songs $SONGS_PER_DAY --max-spotify-qps $SPOTIFY_QPS"
    echo "  $CMD"
    echo
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
echo "Complete! Daily subreddit stats: $SUCCESS_COUNT successes, $FAILED_COUNT failures."
if [ -n "$FAILED_SUBREDDITS" ]; then
    echo "  Failed subreddits: ${FAILED_SUBREDDITS[*]}"
fi
