# Openai to Gemini Proxy

This is a simple proxy to change requests from Openai to Gemini. Only supports the features I need to support, but
you're welcome to open a PR to add more. This can be run in a docker container and is only tested to work with
Nextcloud's AI features.

# Features

Note that a significant amount of config options are not exposed right now.

- Chat Completions (no tool support right now)
- Completions
- Images
- Listing Models