#!/usr/bin/env bash

# Email Mailbox Analyzer Skill
# Analyzes email mailbox usage using imapdu tool
# Extracts settings from Thunderbird and runs analysis

set -e

# Function to extract IMAP servers from Thunderbird prefs.js
extract_imap_servers() {
    local prefs_file="$1"

    # Extract all IMAP server configurations
    # Looking for lines with mail.server.server*.hostname and mail.server.server*.userName
    local servers=()

    # Read the prefs file and extract server info
    while IFS= read -r line; do
        if [[ $line =~ mail\.server\.server([0-9]+)\.hostname.*\"([^\"]+)\" ]]; then
            local server_num="${BASH_REMATCH[1]}"
            local hostname="${BASH_REMATCH[2]}"

            # Skip non-IMAP servers (like "Local Folders" and "smart mailboxes")
            if [[ "$hostname" != "Local Folders" && "$hostname" != "smart mailboxes" ]]; then
                servers["$server_num"]="$hostname"
            fi
        fi
    done < "$prefs_file"

    # Now extract usernames for each server
    local results=()
    for server_num in "${!servers[@]}"; do
        local hostname="${servers[$server_num]}"

        # Find the corresponding username
        local username=""
        while IFS= read -r line; do
            if [[ $line =~ mail\.server\.server$server_num\.userName.*\"([^\"]+)\" ]]; then
                username="${BASH_REMATCH[1]}"
                break
            fi
        done < "$prefs_file"

        if [[ -n "$username" && "$username" != "nobody" ]]; then
            results+=("$username@$hostname")
        fi
    done

    echo "${results[@]}"
}

# Function to run imapdu analysis
run_imapdu_analysis() {
    local server_info="$1"
    local email="${server_info%%@*}"
    local hostname="${server_info##*@}"

    echo "Analyzing mailbox for: $email@$hostname"

    # Run imapdu command
    # Note: This assumes imapdu is installed via uvx
    uvx git+https://github.com/cpackham/imapdu --user "$email" --csv --no-human-readable "$hostname" || {
        echo "Error: Failed to run imapdu for $email@$hostname"
        return 1
    }
}

# Function to process and sort CSV output
process_csv_output() {
    local csv_file="$1"

    echo "Processing CSV output from: $csv_file"

    # Sort by total bytes (column 3) in numerical order
    sort -t, -k3 -n "$csv_file"
}

# Main function
main() {
    local thunderbird_profile="$HOME/.thunderbird/av60ft8s.default-release"
    local prefs_file="$thunderbird_profile/prefs.js"

    # Check if prefs.js exists
    if [[ ! -f "$prefs_file" ]]; then
        echo "Error: Thunderbird prefs.js not found at $prefs_file"
        exit 1
    fi

    echo "Extracting IMAP server information from Thunderbird..."

    # Extract IMAP servers
    local imap_servers=()
    while IFS= read -r server; do
        imap_servers+=("$server")
    done < <(extract_imap_servers "$prefs_file")

    if [[ ${#imap_servers[@]} -eq 0 ]]; then
        echo "No IMAP servers found in Thunderbird configuration"
        exit 1
    fi

    echo "Found ${#imap_servers[@]} IMAP server(s):"
    for i in "${!imap_servers[@]}"; do
        echo "  $((i+1)). ${imap_servers[$i]}"
    done

    # Create output directory
    local output_dir="$HOME/email_analysis_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$output_dir"

    echo "\nRunning analysis for each mailbox..."

    # Analyze each mailbox
    for server in "${imap_servers[@]}"; do
        local email="${server%%@*}"
        local hostname="${server##*@}"
        local output_file="$output_dir/${email}_at_${hostname//./_}.csv"

        echo "\n=== Analyzing $server ==="

        # Run the analysis and save to file
        run_imapdu_analysis "$server" > "$output_file"

        # Process and display sorted results
        echo "\nSorted results for $server:"
        process_csv_output "$output_file"

        echo "\nFull results saved to: $output_file"
    done

    echo "\n=== Analysis Complete ==="
    echo "All results saved in: $output_dir"
    echo "\nTo view individual results:"
    for server in "${imap_servers[@]}"; do
        local email="${server%%@*}"
        local hostname="${server##*@}"
        local output_file="$output_dir/${email}_at_${hostname//./_}.csv"
        echo "  $server: $output_file"
    done
}

# Run main function
main "$@"
