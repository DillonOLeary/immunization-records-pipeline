#!/bin/bash

# Copy the mounted git config to the container file system and make it executable.
# FIXME I don't think this is working. It's close, but on first container build
# FIME it fails. There needs to be a little investigation
# cp /tmp/.gitconfig /home/vscode/.gitconfig && chmod u+w /home/vscode/.gitconfig
# # Install the poetry project
# cd /workspaces/immunization-records-pipeline/data-pipeline && poetry install