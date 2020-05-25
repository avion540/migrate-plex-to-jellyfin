from typing import List

import requests
import urllib3
import click
import re
import sys

from plexapi.server import PlexServer
from jellyfin_client import JellyFinServer


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
def migrate(
    plex_url: str,
    plex_token: str,
    jellyfin_url: str,
    jellyfin_token: str,
    jellyfin_user: str,
    secure: bool,
    debug: bool,
    no_skip: bool,
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
    print(f"{bcolors.OKBLUE}Fetching watched movies from Plex{bcolors.ENDC}")
    plex_movies = plex.library.section("Movies")
    for m in plex_movies.search(unwatched=False):
        info = _extract_provider(data=m.guid)
        info["title"] = m.title
        plex_watched.append(info)
        if debug:
            print(info)

    # Get list of shows that contain watched episodes
    print(f"{bcolors.OKBLUE}Fetching watched TV Shows from Plex{bcolors.ENDC}")
    plex_tvshows = plex.library.section("TV Shows")
    for show in plex_tvshows.search(unwatched=False):
        shows_watched.append(show.title)
        # Get all Plex TV Shows watched episodes
        for e in plex_tvshows.searchEpisodes(unwatched=False):
            # Couldn't figure out how to get just the show title from e,
            # so using regex to strip out all punctuation and spaces to
            # compare and check for show.title existing in e
            # Slicing for the first 16 chars because that's the cutoff in e
            if re.sub('\W+', '',
                      show.title).lower()[:16] in re.sub('\W+', '',
                                                         str(e)).lower():
                info = _extract_provider(data=e.guid)
                info["title"] = show.title
                plex_watched.append(info)
                if debug:
                    print(info)

    # Get all Plex Anime watched episodes
    print(f"{bcolors.OKBLUE}Fetching watched Anime from Plex{bcolors.ENDC}")
    plex_anime = plex.library.section("Anime")
    for show in plex_anime.search(unwatched=False):
        shows_watched.append(show.title)
        # Get all Plex TV Shows watched episodes
        for e in plex_anime.searchEpisodes(unwatched=False):
            # Couldn't figure out how to get just the show title from e,
            # so using regex to strip out all punctuation and spaces to
            # compare and check for show.title existing in e
            # Slicing for the first 16 chars because that's the cutoff in e
            if re.sub('\W+', '',
                      show.title).lower()[:16] in re.sub('\W+', '',
                                                         str(e)).lower():
                info = _extract_provider(data=e.guid)
                info["title"] = show.title
                plex_watched.append(info)
                if debug:
                    print(info)

    # This gets all jellyfin movies since filtering on provider id isn't supported:
    # https://github.com/jellyfin/jellyfin/issues/1990
    print(f"{bcolors.OKBLUE}Fetching Jellyfin library data{bcolors.ENDC}")
    jf_uid = jellyfin.get_user_id(name=jellyfin_user)
    jf_library = jellyfin.get_all(user_id=jf_uid)

    error_items = ""

    # Find Plex items in Jellyfin and mark as watched
    print(f"{bcolors.OKBLUE}Starting Plex to Jellyfin watch status migration{bcolors.ENDC}")
    for w in plex_watched:
        is_episode = False

        # Search
        for d in jf_library:
            if str(d["Type"]) == "Episode" and d["SeriesName"] == w["title"]:
                is_episode = True
                # Test for bad file names
                try:
                    temp = f"{d['ParentIndexNumber']}/{d['IndexNumber']}"
                except Exception as e:
                    print(str(e))
                    pass

                if f"{d['ParentIndexNumber']}/{d['IndexNumber']}" in w[
                        "item_id"]:
                    try:
                        # Get show's ProviderID
                        show_provider_id = jellyfin.get_show_provider_id(
                            user_id=jf_uid, series_id=d["SeriesId"])
                        if (f"{show_provider_id.get(w['provider'])}/{d['ParentIndexNumber']}/{d['IndexNumber']}"
                                == str(w["item_id"])):
                            search_result = d
                            break
                    except Exception as e:
                        print(str(e))
                        print(d)
                        error_items += str(d["Name"])
            elif str(d["Type"]) == "Movie":
                if d["ProviderIds"].get(w["provider"]) == w["item_id"]:
                    print(str(d["Type"]))
                    search_result = d
                    print(f"No. {search_result}")
                    break

        if search_result and not search_result["UserData"]["Played"]:
            jellyfin.mark_watched(user_id=jf_uid, item_id=search_result["Id"])
            if is_episode:
                print(
                    f"{bcolors.OKGREEN}Marked {w['title']} - S{d['ParentIndexNumber']}E{d['IndexNumber']} as watched{bcolors.ENDC}"
                )
            else:
                print(
                    f"{bcolors.OKGREEN}Marked {w['title']} as watched{bcolors.ENDC}"
                )
        elif not search_result:
            if is_episode:
                print(
                    f"{bcolors.WARNING}No matches for {w['title']} - S{d['ParentIndexNumber']}E{d['IndexNumber']}{bcolors.ENDC}"
                )
            else:
                print(
                    f"{bcolors.WARNING}No matches for {w['title']}{bcolors.ENDC}"
                )
            no_matches += w["title"] + " "
            if no_skip:
                sys.exit(1)
        else:
            if debug:
                if is_episode:
                    print(
                        f"{bcolors.OKBLUE}{w['title']} - S{d['ParentIndexNumber']}E{d['IndexNumber']}{bcolors.ENDC}"
                    )
                else:
                    print(f"{bcolors.OKBLUE}{w['title']}{bcolors.ENDC}")
    print(
        f"{bcolors.OKGREEN}Succesfully migrated {len(plex_watched)} items{bcolors.ENDC}"
    )
    print(f"Bad files: {bcolors.WARNING}{error_items}")
    print(f"Unsuccessful imports: {bcolors.WARNING}{no_matches}")


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
        match.group(2).replace("anidb-", ""),
    }


if __name__ == "__main__":
    migrate()
