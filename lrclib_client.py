"""Shared client identification for lrclib.net requests (no CLI).

Imported by update_lyrics.py and lrclib_submitter.py, the two scripts that talk to lrclib.net.

lrclib asks every client to identify itself, and registered applications get higher rate
limits (roughly 90 requests/min per IP with a User-Agent alone, 180/min with a registered
Lrclib-App-Id). See "Client identification" and "Rate Limiting":
https://lrclib.net/docs#implementation-requirements-client-identification

Lrclib-App-Id is the public header for client-side applications: lrclib states the ID "is not a
secret, so it is safe to ship in a client" (the secret one is Lrclib-Api-Key, which is not used
here). An invalid value is rejected with 401 Unauthorized.
"""

USER_AGENT = 'DiscogsMusicManager/1.0 (+https://github.com/koehntopp/discogs)'
LRCLIB_APP_ID = 'Nm2UKEDqSxmkysVsuRQhjw9hWSYkbleD8mGFP7WcBOo'


def lrclib_headers() -> dict[str, str]:
	"""Headers identifying this application on every lrclib.net request."""
	return {'User-Agent': USER_AGENT, 'Lrclib-App-Id': LRCLIB_APP_ID}
