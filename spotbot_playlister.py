#!/usr/bin/env python3

import argparse
from argparse import RawTextHelpFormatter
import logging as log
import praw
import re
import spotipy
import spotipy.util as spotipy_util
from spotipy.oauth2 import SpotifyClientCredentials
import time


# Reddit API Secrets
REDDIT_CLIENT_ID = 'QJhxWK0XUzJEOw'
REDDIT_CLIENT_SECRET = 'TeRVFJJk0xRL_gOfMwxzfxbaTaA'
REDDIT_USER_AGENT = 'web:co.kcrane.spotbot:v0.0.1'

# Spotify API Secrets
#   App page: https://developer.spotify.com/dashboard/applications/c75f29152c694370acf7b43592df8ade
SPOTIFY_CLIENT_ID = 'c75f29152c694370acf7b43592df8ade'
SPOTIFY_CLIENT_SECRET = 'eaa142fff4d04d12aaae01bffc4e00be'

SPOTIFY_USER_ID = '6tq06cdluhvm79h7b7po0mwf2'   # https://www.spotify.com/us/account/overview/
SPOTIFY_PLAYLIST = '/r/{} - Hot Songs'
SPOTIFY_MAX_QPS = 50
SONGS_PER_DAY = 2
PLAYLIST_LENGTH = 40

MUSIC_DOMAINS = [
    'youtube.com',
    'youtu.be',
    'soundcloud.com',
    'spotify.com',
    'open.spotify.com',
    'bandcamp.com',
]

IGNORED_TERMS = [
    'album',
]

AMBIGUOUS_TERMS = [
    ' feat ',
    ' ft ',
    ' ft. ',
]


# TODO:
# - run on lambda
# - wrap in docker
# - set up as cron job on synology; disable lambda
# - get list of music subreddits
# - make new python main script to run command for each one (sequential, add flag for --num-parallel)
# - run it
# - distribute to friends


def init_reddit(client_id, client_secret, user_agent):
    """
    Instantiate our reddit client
    :param str client_id: secret client_id for api access
    :param str client_secret: secret client_secret for api access
    :param str user_agent: unique descriptor of the user account accessing the api
    :return: praw reddit client object
    """
    return praw.Reddit(client_id=client_id,
                       client_secret=client_secret,
                       user_agent=user_agent)


def init_spotify(user_id, client_id, client_secret):
    """
    Instatiate our spotify client after performing authentication handshakes
    :param str user_id: user we log on to spotify as
    :param str client_id: secret client_id for api access
    :param str client_secret: secret client_secret for api access
    :return: spotipy client object
    """
    try:
        sp_token = spotipy_util.prompt_for_user_token(user_id,
                                                      client_id=client_id,
                                                      client_secret=client_secret,
                                                      scope='playlist-modify-public playlist-read-private',
                                                      redirect_uri='http://kcrane.co')
        client_credentials_manager = SpotifyClientCredentials(client_id=client_id,
                                                              client_secret=client_secret)
        return spotipy.Spotify(client_credentials_manager=client_credentials_manager, auth=sp_token)
    except Exception as e:
        log.error('Failed to instantiate Spotify client. Try to run this command on your laptop so you can '
                  'reauthorize this user.', e)


def parse_args():
    """
    Parse command line arguments and validate them.
    :return dict: dictionary of the arguments used
    """
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description='''
Script to find the top songs on reddit each day.
Usage Example:

./spotbot_playlister.py --subreddit popheads --daily
./spotbot_playlister.py --subreddit hiphopheads --new-list --playlist-length 50''')
    parser.add_argument('--subreddit', required=True, type=str, help='The subreddit to find top songs from')
    parser.add_argument('--daily', action='store_true', help='Run a daily job; finds top songs of '
                        'the past day and adds them to an existing playlist')
    parser.add_argument('--weekly', action='store_true', help='Run a weekly job; finds top songs of '
                        'the past week and adds them to an existing playlist')
    parser.add_argument('--new-list', action='store_true', help='Run a job to create a new list; '
                        'deletes any existing playlists for this subreddit, then populates it with '
                        'the top songs until the playlist is full.')
    parser.add_argument('--num-songs', type=int, help='Max number of songs to add. Default: {} for daily '
                        'jobs and {} for a new list'.format(SONGS_PER_DAY, PLAYLIST_LENGTH))
    parser.add_argument('--playlist-length', type=int, default=PLAYLIST_LENGTH,
                        help='Maximum length of a playlist; Default: {}'.format(PLAYLIST_LENGTH))
    parser.add_argument('--max-spotify-qps', type=int, default=SPOTIFY_MAX_QPS,
                        help='Maximum qps of requests to Spotify; Default: {}'.format(SPOTIFY_MAX_QPS))
    parser.add_argument('--logfile', type=str, help='Which file to write logs to', default=None)
    parser.add_argument('--verbose', action='store_true', help='Print more informative log statements')
    args = parser.parse_args()

    # Validate the provided arguments
    if [args.daily, args.weekly, args.new_list].count(True) != 1:
        raise ValueError('Exactly one of --daily, --weekly, or --new-list must be specified')

    if not args.num_songs:
        if args.daily:
            args.num_songs = SONGS_PER_DAY
        elif args.weekly:
            args.num_songs = SONGS_PER_DAY * 5
        else:
            args.num_songs = args.playlist_length

    return args


def configure_logging(subreddit, verbose=False, logfile=None):
    """
    Configure logging for this job
    :param str subreddit: name of the subreddit we're logging
    :param bool verbose: print logs at DEBUG level if true, else INFO
    :param str logfile: write logs to a file instead of stderr
    """
    log_level = log.DEBUG if args.verbose else log.INFO
    log_format = '%(asctime)s %(levelname)s : ({}) %(message)s'.format(args.subreddit)
    if logfile:
        log.basicConfig(level=log_level, format=log_format, filename=logfile)
    else:
        log.basicConfig(level=log_level, format=log_format)


def throttle_maybe(time_start, ops_per_sec):
    """
    Throttle if we are operating too quickly; this method is a no-op if we are
    operating slower than our desired ops_per_sec. Very naive throttling
    implementation (i.e. doesn't account for fluctuation between ops, no token
    bucket).
    """
    time_end = time.time()
    expected_op_duration = 1 / ops_per_sec
    if (time_end - time_start) < expected_op_duration:
        sleep_time = expected_op_duration - (time_end - time_start)
        log.debug('throttle: sleeping for {}ms to main {}qps'.format(round(sleep_time * 1000, 2), ops_per_sec))
        time.sleep(sleep_time)


def extract_song_title(submission_title):
    """
    Parse the reddit submission and return a simplified artist and song title that
    we can pass to spotify. This should:
    - remove all punctuation
    - pull out ambiguous terms that trip up spotify (e.g. 'feat')
    - ignore the term if it's tagged as an album

    :param str submission_title: title of the reddit submission we are processing
    :return str: the cleaned-up song title we will pass to spotify to search
    """
    # Remove punctuation and parens/brackets
    extracted_title = re.sub(r'\[.*?\]|\(.*?\)|\W', ' ', submission_title.lower())

    # Ignore submissions with unhelpful terms (e.g. album submissions)
    for term in IGNORED_TERMS:
        if term in extracted_title:
            return ''

    # Remove ambiguous terms from extracted title
    for term in AMBIGUOUS_TERMS:
        if term in extracted_title:
            extracted_title = extracted_title.replace(term, ' ')

    log.debug('extracted song title "{}" from reddit submission "{}"'.format(
        extracted_title.strip(), submission_title))
    return extracted_title.strip()


def search_for_track(sp, submission_title):
    """
    Search spotify for a song; first parses out the approximate title and
    artist from the reddit submission title, then searches for that in
    spotify.

    :param sp: reference to a spotipy instance
    :param str submission_title: the full title of the reddit submission
    :return str: return the spotify track id that was found, or None if no result
    """
    # Extract a searchable title from the original reddit submission
    search_title = extract_song_title(submission_title)

    if not search_title:
        # Skip any empty title (e.g. album, poorly-formatted)
        return None

    log.debug('searching "{}"'.format(search_title))
    spotify_search_results = sp.search(search_title)

    if spotify_search_results['tracks']['items']:
        # got at least one result back from spotify; return the top match
        artist = spotify_search_results['tracks']['items'][0]['artists'][0]['name']
        track = spotify_search_results['tracks']['items'][0]['name']
        track_id = spotify_search_results['tracks']['items'][0]['id']

        log.debug('found track: {} - {}'.format(artist, track))
        return track_id
    else:
        log.debug('could not find any spotify results for search term {}'.format(search_title))
    return None


def get_or_create_playlist_id(sp, subreddit):
    """
    Return the ID for a subreddit playlist, or create one if it doesn't exist

    :param sp: reference to a spotipy instance
    :param str subreddit: title of the subreddit we want to get the playlist for
    :return int: the spotify id of the playlist we found or created
    """
    target_playlist = SPOTIFY_PLAYLIST.format(subreddit)
    playlists = sp.user_playlists(SPOTIFY_USER_ID)
    for playlist in playlists['items']:
        if playlist['name'] == target_playlist:
            log.debug('found existing playlist "{}"" - playlist_id {}'.format(target_playlist, playlist['id']))
            return playlist['id']

    # playlist doesn't exist, create new one and return id
    log.debug('didnt find playlist "{}"; creating it now'.format(target_playlist))
    new_playlist = sp.user_playlist_create(user=SPOTIFY_USER_ID,
                                           name=target_playlist)
    return new_playlist['id']


def add_songs_to_playlist(sp, playlist_id, track_ids, num_new_songs=PLAYLIST_LENGTH, new_list=False):
    """
    Add songs to a playlist, based on a playlist_id and list of track ids.
    Ignores any songs that are already in this playlist already.

    :param sp: reference to a spotipy instance
    :param int playlist_id: the spotify playlist id that we're adding tracks to
    :param list track_ids: a list of spotify track ids that we're adding to this playlist
    :param int num_new_songs: the maximum number of songs we should add to a playlist
    :param bool new_list: If True, replaces all of the songs in our playlist
    :return int: Return the number of songs added to this playlist
    """
    if new_list:
        # Replace entire playlist with these new songs; scan skip later stages
        new_track_ids = track_ids[:num_new_songs]
        sp.user_playlist_replace_tracks(SPOTIFY_USER_ID, playlist_id, new_track_ids)
        log.debug('adding {} new songs to playlist "{}": {}'.format(
                  len(new_track_ids), playlist_id, new_track_ids))
        return len(new_track_ids)

    # Get all songs in the playlist
    current_tracks = sp.user_playlist(SPOTIFY_USER_ID, playlist_id=playlist_id, fields='tracks')

    # Pull out the track_ids and filter by new songs (not in playlist)
    current_track_ids = [track['track']['id'] for track in current_tracks['tracks']['items']]
    new_track_ids = [track_id for track_id in track_ids if track_id not in current_track_ids]
    new_track_ids = new_track_ids[:num_new_songs]
    log.debug('adding {} new songs to playlist "{}": {}'.format(
        len(new_track_ids), playlist_id, new_track_ids))

    if not new_track_ids:
        # No new tracks to add
        return 0

    # Add up to num_new_songs to playlist, with the order reversed (so top songs are added last)
    sp.user_playlist_add_tracks(SPOTIFY_USER_ID, playlist_id,
                                new_track_ids, position=0)
    return len(new_track_ids)


def clear_oldest_playlist_songs(sp, playlist_id, max_playlist_length=40):
    """
    Remove the oldest songs from a playlist, bringing the playlist down to a maximum length
    of max_playlist_length.

    :param sp: reference to a spotipy instance
    :param int playlist_id: the spotify playlist id that we're trimming
    :param int max_playlist_length: max length we expect the playlist to be
    :return int: new length of the playlist
    """
    current_tracks = sp.user_playlist(SPOTIFY_USER_ID, playlist_id=playlist_id, fields='tracks')
    current_track_ids = [track['track']['id'] for track in current_tracks['tracks']['items']]

    if len(current_track_ids) <= max_playlist_length:
        # Leave early if we have under max_playlist_length songs
        return len(current_track_ids)

    removed_tracks = current_track_ids[max_playlist_length:]
    log.debug('removing {} tracks: {}'.format(len(removed_tracks), removed_tracks))
    sp.user_playlist_remove_all_occurrences_of_tracks(SPOTIFY_USER_ID, playlist_id=playlist_id,
                                                      tracks=removed_tracks)
    return max_playlist_length


# ***** Launch main() with the appropriate arguments *****

def job_daily_top_songs(args):
    """
    Find the top songs of the past day on reddit and add them to an existing spotify playlist.
    :param args: Result of running parse_args()
    """
    return main(subreddit=args.subreddit, new_list=False, num_songs=args.num_songs, time_period='day',
                max_submission_results=100, max_playlist_length=args.playlist_length,
                spotify_qps=args.max_spotify_qps)


def job_weekly_top_songs(args):
    """
    Find the top songs of the past week on reddit and add them to an existing spotify playlist.
    :param args: Result of running parse_args()
    """
    return main(subreddit=args.subreddit, new_list=False, num_songs=args.num_songs, time_period='week',
                max_submission_results=200, max_playlist_length=args.playlist_length,
                spotify_qps=args.max_spotify_qps)


def job_new_list(args):
    """
    Start a new playlist with the top songs from a subreddit. This clears any existing playlists for
    this subreddit. First attempts to fill the playlist from monthly top songs, but expands the search
    to 'yearly' and 'all-time' if not sufficient.
    :param args: Result of running parse_args()
    """
    num_songs_added, new_length = main(subreddit=args.subreddit, new_list=True, num_songs=args.num_songs,
                                       time_period='month', max_submission_results=200,
                                       max_playlist_length=args.playlist_length,
                                       spotify_qps=args.max_spotify_qps)

    for wider_time_period in ['year', 'all']:
        if new_length < args.playlist_length:
            # If we still haven't added enough songs, increase scope of our search and try again (with same list)
            log.debug('Playlist has only {} songs and has not yet reached capacity; re-running search '
                     'for time period "{}"'.format(new_length, wider_time_period))
            songs_added, new_length = main(subreddit=args.subreddit, new_list=False,
                                           num_songs=(args.num_songs - new_length),
                                           time_period=wider_time_period, max_submission_results=200,
                                           max_playlist_length=args.playlist_length,
                                           spotify_qps=args.max_spotify_qps)
            num_songs_added += songs_added
    return (num_songs_added, new_length)


# ***** Main Business Logic *****

def main(subreddit, new_list=False, num_songs=SONGS_PER_DAY, time_period='day',
         max_submission_results=100, max_playlist_length=40, spotify_qps=SPOTIFY_MAX_QPS):
    """
    Run the entire spotbot algorithm.
    - initialize reddit and spotify clients
    - get top submissions on this subreddit over a time period
    - for each submission, try to parse the title and search for its track on spotify
    - get the playlist corresponding to this subreddit; create a new one if nonexistent
    - add these latest songs to our playlist (up to num_songs)
    - delete a corresponding number of songs off of the playlist to trim its length

    :param str subreddit: which subreddit we are searching for songs
    :param bool new_list: if True, will delete a playlist before adding new songs
    :param int num_songs: max number of songs to add to the playlist
    :param str time_period: period over which to search reddit (e.g. day, month, year, all)
    :param int max_submission_results: max numer of reddit submissions to search
    :param int max_playlist_length: max length of the playlist we're changing
    :return tuple: Returns tuple (num_songs_added, new_playlist_length)
    """
    log.info('Finding top songs for /r/{} from time period "{}"; creating a new list? {}; '
             'going to add {} songs, to a max playlist length of {}.'
             .format(subreddit, time_period, new_list, num_songs, max_playlist_length))

    # Initialize Reddit Client
    reddit = init_reddit(client_id=REDDIT_CLIENT_ID,
                         client_secret=REDDIT_CLIENT_SECRET,
                         user_agent=REDDIT_USER_AGENT)

    # Initialize Spotify Client
    spotify = init_spotify(user_id=SPOTIFY_USER_ID,
                           client_id=SPOTIFY_CLIENT_ID,
                           client_secret=SPOTIFY_CLIENT_SECRET)

    # Get top submissions from our music domains (reddit)
    log.debug('searching for top submissions on /r/{} for time period "{}"'.format(subreddit, time_period))
    all_submissions = reddit.subreddit(subreddit).top(time_filter=time_period, limit=max_submission_results)
    music_submissions = [song for song in all_submissions if song.domain in MUSIC_DOMAINS]
    log.debug('found {} posts from our music domains'.format(len(music_submissions)))

    # For each song, pull out the approximate title, search spotify for it
    track_ids = []
    for submission in music_submissions:
        search_start_time = time.time()
        track_id = search_for_track(spotify, submission.title)
        if track_id and track_id not in track_ids:
            log.debug('added track {}; spotify track_id {}'.format(len(track_ids) + 1, track_id))
            track_ids.append(track_id)
        throttle_maybe(search_start_time, spotify_qps)

    # Add each of these songs to a spotify playlist
    playlist_id = get_or_create_playlist_id(spotify, subreddit)
    num_songs_added = add_songs_to_playlist(spotify, playlist_id, track_ids, num_new_songs=num_songs, new_list=new_list)

    # Clear out the oldest songs from our list
    new_length = clear_oldest_playlist_songs(spotify, playlist_id, max_playlist_length=max_playlist_length)
    return (num_songs_added, new_length)


# ***** Entry point for program *****

if __name__ == '__main__':
    # Get cmdline args and config logging
    start_time = time.time()
    args = parse_args()
    configure_logging(subreddit=args.subreddit, verbose=args.verbose, logfile=args.logfile)

    # Run the appropriate job
    if args.daily:
        num_songs_added, new_length = job_daily_top_songs(args)
    elif args.weekly:
        num_songs_added, new_length = job_weekly_top_songs(args)
    else:
        num_songs_added, new_length = job_new_list(args)

    end_time = time.time()
    log.info('Complete! Added {} songs to playlist "{}"; now has {} songs. Completed in {:.2f} seconds.'.format(
             num_songs_added, SPOTIFY_PLAYLIST.format(args.subreddit), new_length, (end_time - start_time)))
