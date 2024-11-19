#!/bin/bash

# Check if Poetry is installed
if ! command -v poetry &> /dev/null; then
  echo "Poetry not found. Installing Poetry..."
  curl -sSL https://install.python-poetry.org | python3 -
  # Add Poetry to PATH
  export PATH="$HOME/.local/bin:$PATH"
  echo "Poetry installed successfully."
fi

# cd into the data-pipeline directory
cd data-pipeline

# Run poetry install
echo "Running 'poetry install'..."
poetry install

# Use AppleScript to select input and output folders
echo "Please select the input folder:"
INPUT_FOLDER=$(osascript -e 'tell application "Finder" to activate' \
                         -e 'tell application "Finder" to POSIX path of (choose folder with prompt "Select the input folder:")')
echo "Selected input folder: $INPUT_FOLDER"

echo "Please select the output folder:"
OUTPUT_FOLDER=$(osascript -e 'tell application "Finder" to activate' \
                         -e 'tell application "Finder" to POSIX path of (choose folder with prompt "Select the output folder:")')
echo "Selected output folder: $OUTPUT_FOLDER"

# Pass the variables to the Poetry project
echo "Passing folders to the Poetry project..."
poetry run python data_pipeline --input_folder "$INPUT_FOLDER" --output_folder "$OUTPUT_FOLDER" --manifest_folder manifests/

echo "Done!"