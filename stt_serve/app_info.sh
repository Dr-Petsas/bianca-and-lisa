#!/bin/sh
# Wo laufen die App-Container, und mit welchen Umschaltern?
docker inspect app-lisa-1 | grep -E '"com.docker.compose.project.working_dir"' | head -1
docker inspect app-lisa-1 | grep -oE '"(TTS_BASE|STT_BASE|LLM_BASE)=[^"]*"'
