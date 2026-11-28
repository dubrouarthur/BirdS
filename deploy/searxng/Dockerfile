# SearXNG for Bird: the official image, a tuned settings.yml, and Railway's $PORT.
# Pinned to a dated release (update by changing the tag after testing).
FROM searxng/searxng:2026.11.26-b5605b8f2

COPY settings.yml /etc/searxng/settings.yml

# Railway gives the port in $PORT; the image serves on $GRANIAN_PORT (8080 by default).
ENTRYPOINT ["/bin/sh", "-c", "export GRANIAN_PORT=\"${PORT:-8080}\"; exec /usr/local/searxng/entrypoint.sh"]
