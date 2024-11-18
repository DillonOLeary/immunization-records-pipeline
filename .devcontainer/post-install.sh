#!/bin/bash

# Copy the mounted git config to the container file system and make it executable.
cp /tmp/.gitconfig /home/vscode/.gitconfig && chmod u+w /home/vscode/.gitconfig
# Install the poetry project
cd /workspaces/immunization-records-pipeline/data-pipeline && poetry install