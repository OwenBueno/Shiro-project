# utils/spotify_client.py
import httpx
import base64
import time
from typing import List, Dict, Optional, Tuple
import asyncio
import logging

from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

SPOTIFY_API_BASE_URL = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

logger = logging.getLogger('spotify_client')

class SpotifyClient:
    def __init__(self):
        self._client_id: Optional[str] = SPOTIFY_CLIENT_ID
        self._client_secret: Optional[str] = SPOTIFY_CLIENT_SECRET
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0  # Timestamp when the token expires
        self._token_lock = asyncio.Lock()
        self._rate_limit_until: float = 0 # Timestamp until which rate limiting is active
        self.MAX_RETRIES = 3
        self.RETRY_DELAY_SECONDS = 5 # Base delay for retries

    async def _ensure_credentials_loaded(self):
        if not self._client_id or not self._client_secret:
            logger.error("Spotify client ID or secret not configured in .env file.")
            raise ValueError("Spotify client ID or secret not configured.")

    async def _get_access_token(self) -> Optional[str]:
        """Fetches a new access token from Spotify using Client Credentials Flow."""
        await self._ensure_credentials_loaded()
        
        auth_header = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        payload = {
            "grant_type": "client_credentials"
        }
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(SPOTIFY_TOKEN_URL, data=payload, headers=headers)
                response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
                token_data = response.json()
                
                self._access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 3600) # Defaults to 1 hour
                self._token_expires_at = time.time() + expires_in - 60 # Subtract 60s buffer
                logger.info(f"Successfully obtained Spotify access token. Expires in {expires_in}s.")
                return self._access_token
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error while getting Spotify token: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"Request error while getting Spotify token: {e}")
        except Exception as e:
            logger.error(f"Unexpected error getting Spotify token: {e}")
        return None

    async def _get_valid_token(self) -> Optional[str]:
        """Returns a valid access token, refreshing if necessary."""
        async with self._token_lock:
            if self._access_token and time.time() < self._token_expires_at:
                return self._access_token
            # Token is invalid or expired, fetch a new one
            logger.info("Spotify token expired or invalid, fetching a new one.")
            return await self._get_access_token()

    async def _make_api_request(self, method: str, endpoint: str, params: Optional[Dict] = None, data: Optional[Dict] = None, attempt=1) -> Optional[Dict]:
        """Makes an authorized request to the Spotify API, handling rate limits and retries."""
        token = await self._get_valid_token()
        if not token:
            return None

        # Respect rate limit if active
        current_time = time.time()
        if current_time < self._rate_limit_until:
            sleep_duration = self._rate_limit_until - current_time
            logger.warning(f"Spotify API rate limit active. Sleeping for {sleep_duration:.2f} seconds.")
            await asyncio.sleep(sleep_duration)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        url = f"{SPOTIFY_API_BASE_URL}{endpoint}"

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.request(method, url, headers=headers, params=params, json=data)

                if response.status_code == 429: # Rate limited
                    retry_after = int(response.headers.get("Retry-After", str(self.RETRY_DELAY_SECONDS * attempt))) # Spotify provides Retry-After in seconds
                    self._rate_limit_until = time.time() + retry_after
                    logger.warning(f"Spotify API rate limit hit (429). Retry-After: {retry_after}s. Endpoint: {endpoint}")
                    if attempt < self.MAX_RETRIES:
                        await asyncio.sleep(retry_after) # Respect Retry-After before retrying
                        return await self._make_api_request(method, endpoint, params, data, attempt + 1)
                    else:
                        logger.error(f"Max retries reached for Spotify API request to {endpoint} after rate limiting.")
                        return None
                
                response.raise_for_status() # Raise for other HTTP errors
                return response.json()
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Spotify API HTTP error: {e.response.status_code} for {method} {url} - {e.response.text}")
            if e.response.status_code == 401: # Token might have been revoked
                logger.info("Spotify token might be invalid (401). Attempting to refresh.")
                async with self._token_lock:
                    self._access_token = None # Force refresh on next call
                if attempt < self.MAX_RETRIES:
                     await asyncio.sleep(self.RETRY_DELAY_SECONDS * attempt)
                     return await self._make_api_request(method, endpoint, params, data, attempt + 1)
        except httpx.RequestError as e:
            logger.error(f"Spotify API request error for {method} {url}: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Spotify API JSON decode error for {method} {url}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during Spotify API request for {method} {url}: {e}")
        
        if attempt < self.MAX_RETRIES:
            await asyncio.sleep(self.RETRY_DELAY_SECONDS * attempt) # General retry for other errors
            return await self._make_api_request(method, endpoint, params, data, attempt + 1)
            
        return None

    async def get_playlist_name_and_tracks(self, playlist_id: str) -> Optional[Tuple[str, List[Dict[str, str]]]]:
        """Fetches playlist name and all tracks (name, primary artist) from a Spotify playlist ID."""
        if not self._client_id or not self._client_secret:
            logger.warning("Spotify credentials not set. Cannot fetch playlist.")
            return None

        # First, get playlist details to find its name and total tracks
        playlist_details_endpoint = f"/playlists/{playlist_id}"
        playlist_info = await self._make_api_request("GET", playlist_details_endpoint, params={"fields": "name,tracks.total"})
        if not playlist_info or 'name' not in playlist_info or 'tracks' not in playlist_info:
            logger.error(f"Could not fetch basic info for Spotify playlist {playlist_id}.")
            return None
        
        playlist_name = playlist_info['name']
        total_tracks = playlist_info['tracks']['total']
        logger.info(f"Fetching tracks for Spotify playlist: '{playlist_name}' (ID: {playlist_id}, Total: {total_tracks})")

        all_tracks: List[Dict[str, str]] = []
        offset = 0
        limit = 50  # Spotify API limit for playlist items per request (max 100, 50 is safer default)

        while offset < total_tracks:
            endpoint = f"/playlists/{playlist_id}/tracks"
            params = {
                "offset": offset,
                "limit": limit,
                "fields": "items(track(name,artists(name),is_local))" # Get track name, artists, and check if local
            }
            response_data = await self._make_api_request("GET", endpoint, params=params)

            if not response_data or "items" not in response_data:
                logger.error(f"Failed to fetch tracks batch for playlist {playlist_id} at offset {offset}.")
                # Optionally, could return partial list or raise error
                break # Stop if a batch fails

            for item in response_data["items"]:
                track_info = item.get("track")
                if track_info and not track_info.get("is_local", False): # Skip local files
                    track_name = track_info.get("name")
                    artists = track_info.get("artists", [])
                    if track_name and artists:
                        primary_artist_name = artists[0].get("name", "Unknown Artist")
                        all_tracks.append({"name": track_name, "artist": primary_artist_name})
            
            if not response_data["items"]: # No more items returned, even if offset < total_tracks (edge case)
                break
            
            offset += limit
            if len(response_data["items"]) < limit: # Last page was smaller than limit
                break
            await asyncio.sleep(0.1) # Small delay to be nice to the API between paginated requests

        logger.info(f"Fetched {len(all_tracks)} tracks from Spotify playlist '{playlist_name}'.")
        return playlist_name, all_tracks

    async def get_album_name_and_tracks(self, album_id: str) -> Optional[Tuple[str, List[Dict[str, str]]]]:
        """Fetches album name and all tracks (name, primary artist) from a Spotify album ID."""
        if not self._client_id or not self._client_secret:
            logger.warning("Spotify credentials not set. Cannot fetch album.")
            return None

        album_details_endpoint = f"/albums/{album_id}"
        album_info = await self._make_api_request("GET", album_details_endpoint, params={"fields": "name,tracks.total,artists"})
        if not album_info or 'name' not in album_info or 'tracks' not in album_info:
            logger.error(f"Could not fetch basic info for Spotify album {album_id}.")
            return None
        
        album_name = album_info['name']
        # Attempt to get album artist if available, otherwise use the first track's artist later as fallback
        album_artists = album_info.get('artists', [])
        album_artist_name = album_artists[0].get("name", "Unknown Artist") if album_artists else "Unknown Artist"
        total_tracks = album_info['tracks']['total']
        logger.info(f"Fetching tracks for Spotify album: '{album_name}' by {album_artist_name} (ID: {album_id}, Total: {total_tracks})")

        all_tracks: List[Dict[str, str]] = []
        offset = 0
        limit = 50  # Spotify API limit for album tracks per request

        while offset < total_tracks:
            endpoint = f"/albums/{album_id}/tracks"
            params = {
                "offset": offset,
                "limit": limit,
                "fields": "items(name,artists(name),is_local)" 
            }
            response_data = await self._make_api_request("GET", endpoint, params=params)

            if not response_data or "items" not in response_data:
                logger.error(f"Failed to fetch tracks batch for album {album_id} at offset {offset}.")
                break

            for item_track_info in response_data["items"]: # item is the track object here directly
                if item_track_info and not item_track_info.get("is_local", False): # Skip local files
                    track_name = item_track_info.get("name")
                    artists = item_track_info.get("artists", [])
                    if track_name and artists:
                        primary_artist_name = artists[0].get("name", "Unknown Artist")
                        all_tracks.append({"name": track_name, "artist": primary_artist_name})
            
            if not response_data["items"] or len(response_data["items"]) < limit:
                break 
            
            offset += limit
            await asyncio.sleep(0.1) 

        logger.info(f"Fetched {len(all_tracks)} tracks from Spotify album '{album_name}'.")
        return album_name, all_tracks

    async def get_track_info(self, track_id: str) -> Optional[Tuple[str, List[Dict[str, str]]]]:
        """Fetches a single track's name and primary artist from a Spotify track ID."""
        if not self._client_id or not self._client_secret:
            logger.warning("Spotify credentials not set. Cannot fetch track.")
            return None

        endpoint = f"/tracks/{track_id}"
        track_info = await self._make_api_request("GET", endpoint)

        if not track_info or "name" not in track_info or "artists" not in track_info:
            logger.error(f"Could not fetch info for Spotify track {track_id}.")
            return None
        
        track_name = track_info["name"]
        artists = track_info.get("artists", [])
        if track_name and artists:
            primary_artist_name = artists[0].get("name", "Unknown Artist")
            # For consistency with other methods, return a list with one track
            # The "album_name" in this context will be the track name itself.
            return track_name, [{"name": track_name, "artist": primary_artist_name}]
        
        logger.error(f"Track name or artist missing in API response for track {track_id}.")
        return None

# Global instance (optional, can also be instantiated per cog or where needed)
spotify_client = SpotifyClient()

async def get_spotify_playlist_tracks(playlist_id: str) -> Optional[Tuple[str, List[Dict[str, str]]]]:
    """Helper function to use the global spotify_client instance."""
    return await spotify_client.get_playlist_name_and_tracks(playlist_id)

async def get_spotify_album_tracks(album_id: str) -> Optional[Tuple[str, List[Dict[str, str]]]]:
    """Helper function to use the global spotify_client instance for albums."""
    return await spotify_client.get_album_name_and_tracks(album_id)

async def get_spotify_track_info(track_id: str) -> Optional[Tuple[str, List[Dict[str, str]]]]:
    """Helper function to use the global spotify_client instance for a single track."""
    return await spotify_client.get_track_info(track_id)


# Example usage (for testing this module directly):
# async def main_test():
#     # Ensure SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are in your .env for this test
#     # and config.py is in a place Python can find it or adjust imports.
#     playlist_url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M" # Example playlist
#     playlist_id_match = re.search(r"playlist/([a-zA-Z0-9]+)", playlist_url)
#     if playlist_id_match:
#         playlist_id = playlist_id_match.group(1)
#         print(f"Extracted playlist ID: {playlist_id}")
#         result = await get_spotify_playlist_tracks(playlist_id)
#         if result:
#             name, tracks = result
#             print(f"Playlist: {name}")
#             for i, track in enumerate(tracks):
#                 print(f"  {i+1}. {track['name']} - {track['artist']}")
#                 if i > 5: break # Print first few
#         else:
#             print("Failed to fetch playlist tracks.")
#     else:
#         print("Invalid Spotify playlist URL format for testing.")

# if __name__ == "__main__":
#    import re # Need re for the test main
#    # Setup basic logging for the test
#    logging.basicConfig(level=logging.INFO,
#                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#    asyncio.run(main_test()) 