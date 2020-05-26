from typing import List

import requests
import urllib3
import click
import re
import sys

from plexapi.server import PlexServer
from jellyfin_client import JellyFinServer

import time


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


@click.command()
@click.option("--plex-url", required=True, help="Plex server url")
@click.option("--plex-token", required=True, help="Plex token")
@click.option("--jellyfin-url", help="Jellyfin server url")
@click.option("--jellyfin-token", help="Jellyfin token")
@click.option("--jellyfin-user", help="Jellyfin user")
@click.option("--secure/--insecure", help="Verify SSL")
@click.option("--debug/--no-debug", help="Print more output")
@click.option("--no-skip/--skip",
              help="Skip when no match it found instead of exiting")
@click.option("--movie-lib-name", help="Plex Movie Library Name i.e. 'Movies'")
@click.option("--show-lib-name",
              help="Plex TV Show Library Name i.e. 'TV Shows'")
@click.option("--anime-lib-name", help="Plex Anime Library Name i.e. 'Anime'")
def migrate(
    plex_url: str,
    plex_token: str,
    jellyfin_url: str,
    jellyfin_token: str,
    jellyfin_user: str,
    secure: bool,
    debug: bool,
    no_skip: bool,
    movie_lib_name: str,
    show_lib_name: str,
    anime_lib_name: str,
):

    # Remove insecure request warnings
    if not secure:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup sessions
    session = requests.Session()
    session.verify = secure
    plex = PlexServer(plex_url, plex_token, session=session)

    jellyfin = JellyFinServer(url=jellyfin_url,
                              api_key=jellyfin_token,
                              session=session)

    # Watched list from Plex. Includes movies and episodes
    plex_watched = []
    # Show titles from Plex that contain watched episodes
    shows_watched = []
    no_matches = ""

    # Get all Plex watched movies
    if movie_lib_name is not None:
        print(
            f"{bcolors.OKBLUE}Fetching watched movies from Plex{bcolors.ENDC}")
        plex_movies = plex.library.section(movie_lib_name)
        for m in plex_movies.search(unwatched=False):
            info = _extract_provider(data=m.guid)
            info["title"] = m.title
            plex_watched.append(info)
            if debug:
                print(info)
    else:
        print("Movie library name was not specified, skipping.")

    # Get list of shows that contain watched episodes
    if show_lib_name is not None:
        print(
            f"{bcolors.OKBLUE}Fetching watched TV Shows from Plex{bcolors.ENDC}"
        )
        plex_tvshows = plex.library.section(show_lib_name)
        watched_shows = plex_tvshows.search(unwatched=False)
        watched_episodes = plex_tvshows.searchEpisodes(unwatched=False)
        for show in watched_shows:
            # Get all Plex TV Shows watched episodes
            for e in watched_episodes:
                shows_watched.append(show.title)
                # Couldn't figure out how to get just the show title from e,
                # so using regex to strip out all punctuation and spaces to
                # compare and check for show.title existing in e
                # Slicing for the first 16 chars because that's the cutoff in e
                if re.sub('\W+', '', show.title).lower()[:16] in re.sub(
                        '\W+', '', str(e)).lower():
                    info = _extract_provider(data=e.guid)
                    info["title"] = show.title
                    plex_watched.append(info)
                    if debug:
                        print(info)
    else:
        print("TV Show library name was not specified, skipping.")

    # Get all Plex Anime watched episodes
    if anime_lib_name is not None:
        print(
            f"{bcolors.OKBLUE}Fetching watched Anime from Plex{bcolors.ENDC}")
        plex_anime = plex.library.section(anime_lib_name)
        watched_anime = plex_anime.search(unwatched=False)
        watched_episodes = plex_anime.searchEpisodes(unwatched=False)

        for show in watched_anime:
            shows_watched.append(show.title)
            # Get all Plex TV Shows watched episodes
            for e in watched_episodes:
                # Couldn't figure out how to get just the show title from e,
                # so using regex to strip out all punctuation and spaces to
                # compare and check for show.title existing in e
                # Slicing for the first 16 chars because that's the cutoff in e
                # TODO:
                # Pulling both Tvdb and AniDB Id's sometimes. Need to clear duplicates and prefer one. AniDB or Tvdb
                # {'provider': 'AniDB', 'item_id': '14440/1/1', 'title': 'A Certain Scientific Accelerator'}
                # {'provider': 'Tvdb', 'item_id': '114921/1/1', 'title': 'A Certain Scientific Accelerator'}
                if re.sub('\W+', '', show.title).lower()[:16] in re.sub(
                        '\W+', '', str(e)).lower():
                    info = _extract_provider(data=e.guid)
                    info["title"] = show.title
                    plex_watched.append(info)
                    if debug:
                        print(info)
    else:
        print("Anime library name was not specified, skipping.")

    # This gets all jellyfin movies since filtering on provider id isn't supported:
    # https://github.com/jellyfin/jellyfin/issues/1990
    print(f"{bcolors.OKBLUE}Fetching Jellyfin library data{bcolors.ENDC}")
    jf_uid = jellyfin.get_user_id(name=jellyfin_user)
    jf_library = jellyfin.get_all(user_id=jf_uid)

    error_items = ""

    # Find Plex items in Jellyfin and mark as watched
    print(
        f"{bcolors.OKBLUE}Starting Plex to Jellyfin watch status migration{bcolors.ENDC}"
    )

    tic = time.perf_counter()
    for w in plex_watched:
        # Search
        for d in jf_library:
            if str(d["Type"]) == "Episode" and d["SeriesName"] == w["title"]:
                #if str(w['title']) == "The Ambition of Oda Nobuna" and d["SeriesName"] == w["title"]:
                try:
                    #print my_string.split("world",1)[1]
                    if f"{d['ParentIndexNumber']}/{d['IndexNumber']}" == w[
                            "item_id"].partition("/")[2]:
                        # Get show's ProviderID
                        show_provider_id = jellyfin.get_show_provider_id(
                            user_id=jf_uid, series_id=d["SeriesId"])
                        if (f"{show_provider_id.get(w['provider'])}/{d['ParentIndexNumber']}/{d['IndexNumber']}"
                                == str(w["item_id"])):
                            search_result = d
                            break
                except Exception as e:
                    if debug:
                        print(f"{bcolors.WARNING}Error: {e}{bcolors.ENDC}")
                        print(d)
                    # Sometimes bad file names cause errors
                    if f"{d['SeriesName']} - {d['Name']}" not in error_items:
                        print(
                            f"{bcolors.WARNING}No metadata found for {d['SeriesName']} - {d['Name']}{bcolors.ENDC}"
                        )
                        error_items += f"\n{d['SeriesName']} - {d['Name']}"
                    continue
            elif str(d["Type"]) == "Movie":
                if d["ProviderIds"].get(w["provider"]) == w["item_id"]:
                    search_result = d
                    break

        if search_result and not search_result["UserData"]["Played"]:
            jellyfin.mark_watched(user_id=jf_uid, item_id=search_result["Id"])
            if str(d["Type"]) == "Episode":
                print(
                    f"{bcolors.OKGREEN}Marked {w['title']} - S{d['ParentIndexNumber']}E{d['IndexNumber']} as watched{bcolors.ENDC}"
                )
            else:
                print(
                    f"{bcolors.OKGREEN}Marked {w['title']} as watched{bcolors.ENDC}"
                )
        elif not search_result:
            if str(d["Type"]) == "Episode":
                season_episode = str(w["item_id"]).split("/")
                print(
                    f"{bcolors.WARNING}No matches for {w['title']} - S{season_episode[1]}E{season_episode[2]}{bcolors.ENDC}"
                )
                no_matches += f"\n{w['title']} - S{season_episode[1]}E{season_episode[2]}"
            else:
                print(
                    f"{bcolors.WARNING}No matches for {w['title']}{bcolors.ENDC}"
                )
                no_matches += f"\n{w['title']}"
            if no_skip:
                sys.exit(1)
        else:
            if debug:
                if str(d["Type"]) == "Episode":
                    print(
                        f"{bcolors.OKBLUE}{w['title']} - S{d['ParentIndexNumber']}E{d['IndexNumber']}{bcolors.ENDC}"
                    )
                else:
                    print(f"{d['Type']} - {d['SeriesName']} - {d['Name']}")
                    print(f"{bcolors.OKBLUE}{w['title']}{bcolors.ENDC}")

        search_result = []

    print(
        f"{bcolors.OKGREEN}Succesfully migrated {len(plex_watched)} items{bcolors.ENDC}"
    )
    if error_items:
        print(
            f"{bcolors.WARNING}Unknown files. Check to make sure they're recognized correctly by Jellyfin: {error_items}{bcolors.ENDC}"
        )
    if no_matches:
        print(f"{bcolors.WARNING}Unsuccessful imports: {no_matches}{bcolors.ENDC}")

    toc = time.perf_counter()
    print(f"Time to mark items as watched: {toc - tic:0.4f} seconds")


def _extract_provider(data: dict) -> dict:
    """Extract Plex provider and return JellyFin compatible data

    Args:
        data (dict): plex episode or movie guid

    Returns:
        dict: provider in JellyFin format and item_id as identifier
    """
    # example: 'com.plexapp.agents.imdb://tt1068680?lang=en'
    # example: 'com.plexapp.agents.thetvdb://248741/1/1?lang=en'
    match = re.match("com\.plexapp\.agents\.(.*):\/\/(.*)\?", data)

    return {
        # Jellyfin uses Imdb and Tvdb (and AniDB if you use the Anime plugin)
        "provider":
        match.group(1).replace("thetvdb", "Tvdb").replace("imdb",
                                                          "Imdb").replace(
                                                              "hama", "AniDB"),
        "item_id":
        match.group(2).replace("anidb-", "").replace("tvdb-", "")
    }


if __name__ == "__main__":
    migrate()
