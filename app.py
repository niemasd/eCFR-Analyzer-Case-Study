import streamlit as st
import requests
import pandas as pd
import numpy as np
import re
import matplotlib.pyplot as plt
import time
from datetime import datetime, timedelta
from collections import defaultdict
from bs4 import BeautifulSoup
import plotly.graph_objects as go
import plotly.express as px
import networkx as nx

# Define global variables with default values
BASE_URL = "https://www.ecfr.gov"
request_timeout = 240  # Default value
skip_problematic_titles = True  # Default value
throttle_delay = 0.2  # Default value
cache_results=True

# Set page config
st.set_page_config(
    page_title="Federal Regulations Word Count Analysis Tool",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Functions to interact with the eCFR API
def get_agencies(force_refresh=False):
    """Fetch all agencies from the API with caching support"""
    cache_key = "agencies_cache"
    
    # Check if we have cached data and caching is enabled
    if not force_refresh and cache_results and cache_key in st.session_state:
        return st.session_state[cache_key]
    
    # If no cache or forced refresh, fetch from API
    url = f"{BASE_URL}/api/admin/v1/agencies.json"
    try:
        response = requests.get(url, timeout=request_timeout)
        if response.status_code == 200:
            agencies = response.json().get("agencies", [])
            # Cache the result if caching is enabled
            if cache_results:
                st.session_state[cache_key] = agencies
            return agencies
        else:
            st.error(f"Error fetching agencies: {response.status_code}")
            return []
    except requests.exceptions.Timeout:
        st.error("Request timed out when fetching agencies. Try increasing the timeout.")
        return []
    except Exception as e:
        st.error(f"Error fetching agencies: {str(e)}")
        return []

def get_titles(force_refresh=False):
    """Fetch summary information about all titles with caching support"""
    cache_key = "titles_cache"
    
    # Check if we have cached data and caching is enabled
    if not force_refresh and cache_results and cache_key in st.session_state:
        return st.session_state[cache_key]
    
    # If no cache or forced refresh, fetch from API
    url = f"{BASE_URL}/api/versioner/v1/titles.json"
    try:
        response = requests.get(url, timeout=request_timeout)
        if response.status_code == 200:
            titles = response.json().get("titles", [])
            # Cache the result if caching is enabled
            if cache_results:
                st.session_state[cache_key] = titles
            return titles
        else:
            st.error(f"Error fetching titles: {response.status_code}")
            return []
    except requests.exceptions.Timeout:
        st.error("Request timed out when fetching titles. Try increasing the timeout.")
        return []
    except Exception as e:
        st.error(f"Error fetching titles: {str(e)}")
        return []

def get_title_content(title_number, date, max_retries=1, force_refresh=False):
    """Fetch XML content for a title on a specific date with retry capability and caching"""
    cache_key = f"title_content_{title_number}_{date}"
    
    # Check if we have cached data and caching is enabled
    if not force_refresh and cache_results and cache_key in st.session_state:
        return st.session_state[cache_key]
    
    # Skip known problematic titles if option is enabled
    if skip_problematic_titles and title_number in [7, 10, 40, 42, 45]:
        st.warning(f"Skipping Title {title_number} as it's known to cause timeouts due to its size")
        return None
    
    url = f"{BASE_URL}/api/versioner/v1/full/{date}/title-{title_number}.xml"
    
    retries = 0
    while retries <= max_retries:
        try:
            response = requests.get(url, timeout=request_timeout)
            if response.status_code == 200:
                content = response.text
                # Cache the result if caching is enabled
                if cache_results:
                    st.session_state[cache_key] = content
                return content
            elif response.status_code == 504:
                retries += 1
                if retries <= max_retries:
                    st.warning(f"Gateway timeout (504) for Title {title_number}. Retrying ({retries}/{max_retries})...")
                    time.sleep(throttle_delay * 2)  # Wait longer between retries
                else:
                    st.warning(f"Gateway timeout (504) for Title {title_number} after {max_retries} retries. Try increasing the timeout or skipping large titles.")
                    return None
            elif response.status_code == 404:
                st.warning(f"Title {title_number} not available for date {date}")
                return None
            else:
                st.error(f"Error fetching title {title_number} content: {response.status_code}")
                return None
        except requests.exceptions.Timeout:
            retries += 1
            if retries <= max_retries:
                st.warning(f"Request timed out for Title {title_number}. Retrying ({retries}/{max_retries})...")
                time.sleep(throttle_delay * 2)
            else:
                st.warning(f"Request timed out for Title {title_number} after {max_retries} retries.")
                return None
        except Exception as e:
            st.error(f"Error fetching title {title_number} content: {str(e)}")
            return None

def count_words_in_xml(xml_content):
    """Count words in XML content using BeautifulSoup"""
    if not xml_content:
        return 0
    
    try:
        # Parse XML with BeautifulSoup
        soup = BeautifulSoup(xml_content, 'lxml-xml')
        
        # Extract all text
        text = soup.get_text()
        
        # Count words
        words = re.findall(r'\b\w+\b', text)
        return len(words)
    except Exception as e:
        st.warning(f"Error parsing XML: {str(e)}")
        # Fall back to simple regex approach
        text_without_tags = re.sub(r'<[^>]+>', ' ', xml_content)
        words = re.findall(r'\b\w+\b', text_without_tags)
        return len(words)

def create_agency_title_mapping(agencies):
    """Create a mapping of agencies to the titles they regulate"""
    agency_to_titles = defaultdict(set)
    
    for agency in agencies:
        agency_name = agency["name"]
        
        # Add titles directly regulated by this agency
        if "cfr_references" in agency:
            for ref in agency["cfr_references"]:
                if "title" in ref:
                    agency_to_titles[agency_name].add(ref["title"])
        
        # Process child agencies
        if "children" in agency and agency["children"]:
            for child in agency["children"]:
                child_name = child["name"]
                if "cfr_references" in child:
                    for ref in child["cfr_references"]:
                        if "title" in ref:
                            agency_to_titles[child_name].add(ref["title"])
    
    return agency_to_titles

def extract_agency_hierarchy(agencies):
    """Extract the hierarchy of agencies for visualization"""
    nodes = []
    edges = []
    
    # Function to process an agency and its children
    def process_agency(agency, parent=None):
        agency_id = agency["slug"]
        agency_name = agency["name"]
        
        # Add node
        nodes.append({
            "id": agency_id,
            "name": agency_name,
            "short_name": agency.get("short_name", ""),
            "is_parent": len(agency.get("children", [])) > 0
        })
        
        # Add edge if there is a parent
        if parent:
            edges.append((parent, agency_id))
        
        # Process children
        for child in agency.get("children", []):
            process_agency(child, agency_id)
    
    # Process all top-level agencies
    for agency in agencies:
        process_agency(agency)
    
    return nodes, edges

def create_agency_hierarchy_graph(agencies):
    """Create a NetworkX graph for agency hierarchy"""
    nodes, edges = extract_agency_hierarchy(agencies)
    
    G = nx.DiGraph()
    
    # Add nodes with attributes
    for node in nodes:
        G.add_node(node["id"], 
                   name=node["name"], 
                   short_name=node["short_name"],
                   is_parent=node["is_parent"])
    
    # Add edges
    G.add_edges_from(edges)
    
    return G, nodes

def calculate_word_counts_over_time(agencies, titles_info, years, max_titles, throttle_delay):
    """Calculate word counts for each agency over multiple years"""
    # Get agency to title mapping
    agency_to_titles = create_agency_title_mapping(agencies)
    
    # Create reverse mapping (title -> agencies)
    title_to_agencies = defaultdict(list)
    for agency, titles in agency_to_titles.items():
        for title in titles:
            title_to_agencies[title].append(agency)
    
    # Dictionary to store word counts by year and agency
    word_counts_by_year = {}
    
    # Process titles for each year
    for year in years:
        target_date = f"{year}-01-01"
        st.write(f"Processing year: {year}")
        
        progress_bar = st.progress(0)
        
        # Dictionary to store word counts by title for this year
        title_word_counts = {}
        
        # Process titles (limited to max_titles)
        process_size = min(max_titles, len(titles_info))
        
        for i, title_info in enumerate(titles_info[:process_size]):
            title_number = title_info["number"]
            title_name = title_info.get("name", "Unknown")
            latest_date = title_info["latest_amended_on"]
            
            # Update progress
            progress = (i + 1) / process_size
            progress_bar.progress(progress)
            
            # Skip reserved titles
            if title_info.get("reserved", False):
                continue
            
            # Determine date to use
            use_date = target_date
            if datetime.strptime(latest_date, "%Y-%m-%d") < datetime.strptime(target_date, "%Y-%m-%d"):
                use_date = latest_date
            
            # Fetch and process content
            title_content = get_title_content(title_number, use_date)
            
            if title_content:
                word_count = count_words_in_xml(title_content)
                title_word_counts[title_number] = word_count
            
            # Add delay to avoid rate limiting
            time.sleep(throttle_delay)
        
        # Calculate word counts per agency for this year
        agency_word_counts = defaultdict(int)
        for title, word_count in title_word_counts.items():
            agencies_for_title = title_to_agencies.get(title, [])
            if agencies_for_title:
                # If a title is regulated by multiple agencies, distribute the word count
                count_per_agency = word_count / len(agencies_for_title)
                for agency in agencies_for_title:
                    agency_word_counts[agency] += count_per_agency
        
        # Store results for this year
        word_counts_by_year[year] = dict(agency_word_counts)
        
        progress_bar.empty()
    
    return word_counts_by_year

def main():
    global request_timeout, skip_problematic_titles, throttle_delay, cache_results
    
    st.title("Code of Federal Regulations Analyzer")
    st.write("""
    This app analyzes the word count of federal regulations per agency using the Electronic Code of Federal Regulations (eCFR) API.
    """)
    
    # Sidebar configuration
    st.sidebar.header("Analysis Configuration")
    
    # Date input with default of 2025-01-01
    default_date = datetime(2025, 1, 1)
    target_date = st.sidebar.date_input("Select a Date Cutoff", value=default_date)
    target_date_str = target_date.strftime("%Y-%m-%d")
    
    # Sample size selector
    max_titles = st.sidebar.slider("Number of titles to process", 1, 50, 5, 
                                  help="Higher values provide more complete results but take longer to process")
    
    # Advanced options
    with st.sidebar.expander("Advanced Options"):
        cache_results = st.checkbox("Cache results", value=True, 
                                   help="Store results to avoid reprocessing if parameters don't change")
        throttle_delay = st.slider("API request delay (seconds)", 0.1, 2.0, 0.2, 0.1,
                                  help="Increase to avoid API rate limiting")
        request_timeout = st.slider("Request timeout (seconds)", 30, 600, 240, 30,
                                   help="Maximum time to wait for API response before timing out (helps with 504 errors)")
        skip_problematic_titles = st.checkbox("Skip known large titles", value=True,
                                            help="Skip titles known to cause timeouts (7, 12, 20, 21, 31, 40, 42, 46, 47, 48, 49, 50)")
    
    # Analytics tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Agency Analysis", "Title Analysis", "Agency Hierarchy", "Word Count Over Time", "Regulatory Composition",'About'])
    
    with tab1:
        st.header("Regulation Word Count by Agency")

        if st.button("Calculate Word Counts", type="primary"):
            # Create a cache key based on the parameters
            cache_key = f"agency_analysis_{max_titles}_{target_date_str}_{skip_problematic_titles}_{request_timeout}_{throttle_delay}"

            # Check if we have cached results and caching is enabled
            if cache_results and cache_key in st.session_state:
                st.success("Using cached results. Toggle 'Cache results' off to force recalculation.")

                # Retrieve cached data
                agencies = st.session_state[f"{cache_key}_agencies"]
                titles_info = st.session_state[f"{cache_key}_titles_info"]
                title_word_counts = st.session_state[f"{cache_key}_title_word_counts"]
                df = st.session_state[f"{cache_key}_all_agencies_df"]
                senior_df = st.session_state[f"{cache_key}_senior_agencies_df"]
                title_df = st.session_state[f"{cache_key}_title_df"]
                agency_word_counts = st.session_state[f"{cache_key}_agency_word_counts"]

                # Store in session state for other tabs
                st.session_state.agencies = agencies
                st.session_state.titles_info = titles_info
                st.session_state.title_df = title_df
                st.session_state.title_word_counts = title_word_counts
                st.session_state.agency_word_counts = agency_word_counts
                st.session_state.all_agencies_df = df
                st.session_state.senior_agencies_df = senior_df
            else:
                # Initialize progress tracking
                progress_bar = st.progress(0)
                status_text = st.empty()
                results_placeholder = st.empty()

                try:
                    status_text.text("Fetching agencies and titles...")
                    # Force refresh if cache disabled
                    agencies = get_agencies(force_refresh=not cache_results)
                    titles_info = get_titles(force_refresh=not cache_results)

                    # Store in session state for other tabs
                    st.session_state.agencies = agencies
                    st.session_state.titles_info = titles_info

                    # Create agency-title mappings
                    agency_to_titles = create_agency_title_mapping(agencies)
                    title_to_agencies = defaultdict(list)
                    for agency, titles in agency_to_titles.items():
                        for title in titles:
                            title_to_agencies[title].append(agency)

                    # Identify most senior agencies (those with no parent)
                    all_child_names = set()
                    for agency in agencies:
                        for child in agency.get("children", []):
                            all_child_names.add(child["name"])

                    # Process titles
                    title_word_counts = {}
                    process_size = min(max_titles, len(titles_info))

                    col1, col2 = st.columns(2)
                    with col1:
                        st.subheader("Processing Status")
                        processing_status = st.empty()

                    with col2:
                        st.subheader("Current Statistics")
                        stats_display = st.empty()

                    for i, title_info in enumerate(titles_info[:process_size]):
                        title_number = title_info["number"]
                        title_name = title_info.get("name", "Unknown")
                        latest_date = title_info["latest_amended_on"]

                        # Update progress
                        progress = (i + 1) / process_size
                        progress_bar.progress(progress)
                        processing_status.write(f"Processing title {i+1} of {process_size}: Title {title_number} - {title_name}")

                        # Skip reserved titles
                        if title_info.get("reserved", False):
                            processing_status.write(f"Skipping reserved title {title_number}")
                            continue

                        # Determine date to use
                        use_date = target_date_str
                        if datetime.strptime(latest_date, "%Y-%m-%d") < datetime.strptime(target_date_str, "%Y-%m-%d"):
                            use_date = latest_date
                            processing_status.write(f"Using latest available date ({latest_date}) for Title {title_number}")

                        # Fetch and process content with cache control
                        title_content = get_title_content(title_number, use_date, force_refresh=not cache_results)

                        if title_content:
                            word_count = count_words_in_xml(title_content)
                            title_word_counts[title_number] = word_count

                            # Update stats
                            stats_display.write(f"""
                            **Title {title_number}**
                            - Name: {title_name}
                            - Word count: {word_count:,}
                            - Date analyzed: {use_date}
                            """)

                        # Add delay to avoid rate limiting
                        time.sleep(throttle_delay)

                    # Calculate word counts per agency
                    agency_word_counts = defaultdict(int)
                    for title, word_count in title_word_counts.items():
                        agencies_for_title = title_to_agencies.get(title, [])
                        if agencies_for_title:
                            # If a title is regulated by multiple agencies, distribute the word count
                            count_per_agency = word_count / len(agencies_for_title)
                            for agency in agencies_for_title:
                                agency_word_counts[agency] += count_per_agency

                    # Create DataFrame with all agencies
                    df = pd.DataFrame(list(agency_word_counts.items()), columns=["Agency", "Word Count"])
                    df["Word Count"] = df["Word Count"].astype(int)
                    df = df.sort_values(by="Word Count", ascending=False).reset_index(drop=True)

                    # Create a DataFrame with only top-level (senior) agencies
                    senior_agencies = [agency["name"] for agency in agencies]
                    senior_df = df[df["Agency"].isin(senior_agencies)]
                    senior_df = senior_df.sort_values(by="Word Count", ascending=False).reset_index(drop=True)

                    # Create title word count DataFrame
                    title_df = pd.DataFrame({
                        "Title": [f"Title {title}" for title in title_word_counts.keys()],
                        "Word Count": list(title_word_counts.values())
                    })
                    title_df = title_df.sort_values(by="Word Count", ascending=False).reset_index(drop=True)

                    # Store data in session state
                    st.session_state.agency_word_counts = agency_word_counts
                    st.session_state.all_agencies_df = df
                    st.session_state.senior_agencies_df = senior_df
                    st.session_state.title_df = title_df
                    st.session_state.title_word_counts = title_word_counts

                    # Cache results if enabled
                    if cache_results:
                        st.session_state[f"{cache_key}_agencies"] = agencies
                        st.session_state[f"{cache_key}_titles_info"] = titles_info
                        st.session_state[f"{cache_key}_title_word_counts"] = title_word_counts
                        st.session_state[f"{cache_key}_all_agencies_df"] = df
                        st.session_state[f"{cache_key}_senior_agencies_df"] = senior_df
                        st.session_state[f"{cache_key}_title_df"] = title_df
                        st.session_state[f"{cache_key}_agency_word_counts"] = agency_word_counts

                    # Clear placeholders
                    progress_bar.empty()
                    status_text.empty()
                    processing_status.empty()
                    stats_display.empty()

                    # Display results
                    results_placeholder.write("### Results")

                    # Add tabs for different views
                    results_tab1, results_tab2 = st.tabs(["Senior Agencies", "All Agencies"])

                    with results_tab1:
                        st.write(f"Showing {len(senior_df)} Agencies")
                        st.dataframe(senior_df, use_container_width=True)

                        # Visualization for senior agencies only
                        st.subheader("Top 10 Agencies by Word Count")
                        fig, ax = plt.subplots(figsize=(12, 6))
                        top_df = senior_df.head(10) if len(senior_df) > 10 else senior_df
                        bars = ax.bar(top_df["Agency"], top_df["Word Count"])

                        # Calculate the maximum bar height for y-axis adjustment
                        max_height = top_df["Word Count"].max()

                        # Add value labels on top of each bar
                        for bar in bars:
                            height = bar.get_height()
                            ax.text(bar.get_x() + bar.get_width()/2., height + max_height*0.01,
                                f'{height:,}', ha='center', va='bottom', rotation=0)

                        # Set y-axis limit with 15% padding to avoid clipping
                        ax.set_ylim(0, max_height * 1.15)

                        plt.xticks(rotation=45, ha="right")
                        plt.title(f"Top Agencies by Regulation Word Count (as of {target_date_str})")
                        plt.ylabel("Word Count")
                        plt.tight_layout()
                        st.pyplot(fig)

                    with results_tab2:
                        st.write(f"Showing all {len(df)} agencies (including child agencies)")
                        st.dataframe(df, use_container_width=True)

                    # Download button for results
                    csv = df.to_csv(index=False)
                    st.download_button(
                        label="Download complete agency data as CSV",
                        data=csv,
                        file_name=f"regulation_wordcount_by_agency_{target_date_str}.csv",
                        mime="text/csv"
                    )

                    # Store title data for the second tab
                    st.session_state.title_df = title_df
                    st.session_state.title_word_counts = title_word_counts

                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")
                    st.write("This could be due to API rate limits or unavailability. Please try again later.")
    
    with tab2:
        st.header("Title-Level Analysis")
        
        if 'title_df' in st.session_state:
            st.subheader("Word Count by Title")
            st.dataframe(st.session_state.title_df, use_container_width=True)
            
            # Visualization for titles
            st.subheader("Top 10 Titles by Word Count")
            fig, ax = plt.subplots(figsize=(12, 6))
            top_title_df = st.session_state.title_df.head(10)
            bars = ax.bar(top_title_df["Title"], top_title_df["Word Count"])
            
            # Add value labels
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 5,
                       f'{height:,}', ha='center', va='bottom', rotation=0)
            
            plt.xticks(rotation=45, ha="right")
            plt.title(f"Top Titles by Word Count (as of {target_date_str})")
            plt.ylabel("Word Count")
            plt.tight_layout()
            st.pyplot(fig)
            
            # Download button for title data
            csv = st.session_state.title_df.to_csv(index=False)
            st.download_button(
                label="Download title data as CSV",
                data=csv,
                file_name=f"regulation_wordcount_by_title_{target_date_str}.csv",
                mime="text/csv"
            )
        else:
            st.info("Please run the analysis in the 'Agency Analysis' tab first to view title-level data.")
    
    with tab3:
        st.header("Agency Hierarchy Visualization")

        # Check if agencies data is available or fetch it
        if 'agencies' not in st.session_state:
            with st.spinner("Fetching agency data..."):
                st.session_state.agencies = get_agencies()

        if st.session_state.agencies:
            # Get top-level agencies (most senior parents)
            top_level_agencies = [a for a in st.session_state.agencies]

            # Find agencies with children (parents)
            parent_agencies = []

            # Function to find parent agencies recursively
            def find_parent_agencies(agency_list):
                for agency in agency_list:
                    # Check if this agency has children
                    if agency.get("children", []) and len(agency["children"]) > 0:
                        parent_agencies.append(agency)
                        # Also check children recursively for any that might be parents
                        find_parent_agencies(agency["children"])

            # Process all agencies to find parent ones
            find_parent_agencies(top_level_agencies)

            # Find independent agencies (those not listed as children of any other agency)
            all_child_slugs = set()
            for agency in st.session_state.agencies:
                for child in agency.get("children", []):
                    all_child_slugs.add(child["slug"])

            # Collect independent agencies that are not top-level
            independent_agencies = []

            # Function to find independent agencies recursively
            def find_independent_agencies(agency_list):
                for agency in agency_list:
                    # Check if this agency has children
                    if agency.get("children", []):
                        # Check children recursively
                        find_independent_agencies(agency["children"])
                    # If this agency appears in top level but isn't a child of anyone, it's independent
                    elif agency["slug"] not in all_child_slugs:
                        independent_agencies.append(agency)

            # Process all agencies to find independent ones
            find_independent_agencies(top_level_agencies)

            # Display agency counts
            total_agencies = sum(1 for a in top_level_agencies) + sum(len(a.get("children", [])) for a in top_level_agencies)
            st.write(f"Total Agencies: {total_agencies}")
            st.write(f"Parent Agencies: {len(parent_agencies)}")
            st.write(f"Independent Agencies (No Parent): {len(independent_agencies)}")

            # Create dropdown options - only parent agencies (those with children) and an option for independent agencies
            dropdown_options = ["All Agencies", "Agencies Without Parent"] + [a["name"] for a in parent_agencies]

            selected_option = st.selectbox(
                "Filter by agency category:",
                dropdown_options
            )

            # Create a function to build a hierarchical sunburst chart
            def build_sunburst_data(agencies, independent_agencies, parent_agencies, selected_option):
                data = []

                # Add root node
                data.append({
                    "id": "root",
                    "parent": "",
                    "name": "Federal Agencies",
                    "value": 1
                })

                # Process each agency
                def process_agency(agency, parent="root", include=True):
                    if not include:
                        return

                    agency_id = agency["slug"]
                    agency_name = agency["name"]

                    # Add this agency
                    data.append({
                        "id": agency_id,
                        "parent": parent,
                        "name": agency_name,
                        "value": 1
                    })

                    # Add children
                    for child in agency.get("children", []):
                        process_agency(child, agency_id, include)

                # Handle different filter options
                if selected_option == "All Agencies":
                    # Include all agencies
                    for agency in agencies:
                        process_agency(agency)

                elif selected_option == "Agencies Without Parent":
                    # Create a virtual parent for independent agencies
                    data.append({
                        "id": "independent",
                        "parent": "root",
                        "name": "Agencies Without Parent",
                        "value": 1
                    })

                    # Add all independent agencies under this virtual parent
                    for agency in independent_agencies:
                        agency_id = agency["slug"]
                        agency_name = agency["name"]

                        data.append({
                            "id": agency_id,
                            "parent": "independent",
                            "name": agency_name,
                            "value": 1
                        })

                else:
                    # Find the selected parent agency
                    selected_agency = next((a for a in parent_agencies if a["name"] == selected_option), None)
                    if selected_agency:
                        process_agency(selected_agency)
                        

                return pd.DataFrame(data)

            # Build the data based on selection
            sunburst_df = build_sunburst_data(top_level_agencies, independent_agencies, parent_agencies, selected_option)

            # Create the sunburst chart
            fig = px.sunburst(
                sunburst_df,
                ids='id',
                parents='parent',
                names='name',
                title=f"Agency Hierarchy: {selected_option}",
                height=700
            )

            fig.update_layout(margin=dict(t=30, l=0, r=0, b=0))

            st.plotly_chart(fig, use_container_width=True)

            # Also provide a table view
            st.subheader("Agency Table")

            # Create a more readable table
            table_data = []

            def process_agency_for_table(agency, level=0):
                agency_name = agency["name"]
                agency_id = agency["slug"]

                # Add this agency
                table_data.append({
                    "Agency": "  " * level + agency_name,
                    "Level": level,
                    "ID": agency_id,
                    "Short Name": agency.get("short_name", ""),
                    "Parent": "Yes" if agency.get("children", []) else "No"
                })

                # Add children
                for child in sorted(agency.get("children", []), key=lambda x: x["name"]):
                    process_agency_for_table(child, level + 1)

            # Process agencies based on selection
            if selected_option == "All Agencies":
                # Include all top-level agencies
                for agency in sorted(top_level_agencies, key=lambda x: x["name"]):
                    process_agency_for_table(agency)

            elif selected_option == "Agencies Without Parent":
                # Include only independent agencies
                for agency in sorted(independent_agencies, key=lambda x: x["name"]):
                    process_agency_for_table(agency, 0)  # Level 0 since they're all top-level in this view

            else:
                # Find and include only the selected parent agency
                selected_agency = next((a for a in parent_agencies if a["name"] == selected_option), None)
                if selected_agency:
                    process_agency_for_table(selected_agency)

            # Create the table DataFrame
            table_df = pd.DataFrame(table_data)
            if not table_df.empty:
                st.dataframe(table_df[["Agency", "Short Name", "Parent"]], use_container_width=True)

                # Show count of agencies in this view
                st.write(f"Showing {len(table_df)} agencies in this view")

                # Add download button for the current view
                csv = table_df.to_csv(index=False)
                safe_filename = selected_option.replace(" ", "_").replace("/", "_")
                st.download_button(
                    label="Download agency list as CSV",
                    data=csv,
                    file_name=f"agencies_{safe_filename}.csv",
                    mime="text/csv"
                )
            else:
                st.info("No agencies to display with the current filter.")

        else:
            st.warning("No agency data available. Please run the analysis in the 'Agency Analysis' tab first.")
    
    with tab4:
        st.header("Word Count Over Time")

        # Year range selection
        st.subheader("Select Years to Analyze")

        col1, col2 = st.columns(2)
        with col1:
            start_year = st.number_input("Start Year", min_value=2010, max_value=2025, value=2022)
        with col2:
            end_year = st.number_input("End Year", min_value=2010, max_value=2025, value=2024)

        if end_year < start_year:
            st.error("End year must be greater than or equal to start year.")
        else:
            years_to_analyze = list(range(start_year, end_year + 1))

            # Check if agencies data is available or fetch it
            if 'agencies' not in st.session_state:
                with st.spinner("Fetching agency data..."):
                    st.session_state.agencies = get_agencies(force_refresh=not cache_results)

            # Get all agencies
            if st.session_state.agencies:
                # Extract all agency names
                all_agency_names = []

                def collect_agency_names(agency_list):
                    for agency in agency_list:
                        all_agency_names.append(agency["name"])
                        if "children" in agency and agency["children"]:
                            collect_agency_names(agency["children"])

                collect_agency_names(st.session_state.agencies)
                all_agency_names = sorted(all_agency_names)

                # Agency selection
                st.subheader("Select Agencies to Analyze")

                # Option to select all
                select_all = st.checkbox("Select All Agencies", value=False)

                if select_all:
                    selected_agencies = all_agency_names
                    st.info(f"All {len(all_agency_names)} agencies selected")
                else:
                    # Multi-select for agencies
                    selected_agencies = st.multiselect(
                        "Choose agencies to analyze:",
                        options=all_agency_names,
                        default=all_agency_names[:5] if len(all_agency_names) >= 5 else all_agency_names
                    )

                    if not selected_agencies:
                        st.warning("Please select at least one agency to analyze.")
                    else:
                        st.info(f"{len(selected_agencies)} agencies selected")

                if selected_agencies:
                    if st.button("Calculate Word Counts Over Time", type="primary"):
                        # Create a cache key based on the parameters
                        # Sort and join selected_agencies for a consistent key regardless of selection order
                        agencies_key = "_".join(sorted([agency.replace(" ", "_")[:10] for agency in selected_agencies]))
                        cache_key = f"wordcount_time_{start_year}_{end_year}_{max_titles}_{target_date_str}_{skip_problematic_titles}_{request_timeout}"

                        # Check if we have cached results and caching is enabled
                        if cache_results and cache_key in st.session_state:
                            st.success("Using cached results. Toggle 'Cache results' off to force recalculation.")

                            # Retrieve cached data
                            word_counts_by_year = st.session_state[f"{cache_key}_word_counts_by_year"]
                            time_df = st.session_state[f"{cache_key}_time_df"]
                        else:
                            # Check if titles data is available or fetch it
                            if 'titles_info' not in st.session_state:
                                with st.spinner("Fetching titles data..."):
                                    st.session_state.titles_info = get_titles(force_refresh=not cache_results)

                            # Calculate word counts for each year
                            with st.spinner(f"Calculating word counts for years {start_year}-{end_year}..."):
                                word_counts_by_year = calculate_word_counts_over_time(
                                    st.session_state.agencies,
                                    st.session_state.titles_info,
                                    years_to_analyze,
                                    max_titles,
                                    throttle_delay
                                )

                            # Create DataFrame for plotting
                            plot_data = []

                            for year, agency_counts in word_counts_by_year.items():
                                for agency, count in agency_counts.items():
                                    if agency in selected_agencies:
                                        plot_data.append({
                                            "Year": year,
                                            "Agency": agency,
                                            "Word Count": int(count)
                                        })

                            time_df = pd.DataFrame(plot_data)

                            # Cache results if enabled
                            if cache_results:
                                st.session_state[f"{cache_key}_word_counts_by_year"] = word_counts_by_year
                                st.session_state[f"{cache_key}_time_df"] = time_df
                                # Store the cache key itself for reference
                                st.session_state[cache_key] = True

                        # Store in session state for potential use in other tabs
                        st.session_state.word_counts_by_year = word_counts_by_year
                        st.session_state.time_df = time_df

                        if time_df.empty:
                            st.warning("No data available for the selected agencies and years.")
                        else:
                            # Create the interactive line chart for all selected agencies
                            st.subheader(f"Word Count Trends for {len(selected_agencies)} Selected Agencies")

                            # Use color if 10 or fewer agencies, otherwise use grayscale for readability
                            use_color = len(selected_agencies) <= 10

                            if use_color:
                                fig = px.line(
                                    time_df,
                                    x="Year",
                                    y="Word Count",
                                    color="Agency",
                                    markers=True,
                                    title="Regulation Word Count Over Time",
                                    hover_data=["Agency", "Word Count"]
                                )
                            else:
                                # Create a custom plot with lighter lines for better viewing many agencies
                                fig = px.line(
                                    time_df,
                                    x="Year",
                                    y="Word Count",
                                    color="Agency",
                                    markers=True,
                                    title="Regulation Word Count Over Time",
                                    hover_data=["Agency", "Word Count"],
                                    color_discrete_sequence=px.colors.sequential.Greys[3:]
                                )
                                # Adjust line opacity
                                fig.update_traces(opacity=0.7, line=dict(width=1))

                            # Ensure X-axis shows only whole years
                            fig.update_xaxes(
                                tickmode='array',
                                tickvals=years_to_analyze,
                                ticktext=[str(year) for year in years_to_analyze],
                                dtick=1
                            )

                            fig.update_layout(
                                xaxis_title="Year",
                                yaxis_title="Word Count",
                                legend_title="Agency",
                                hovermode="closest"
                            )

                            st.plotly_chart(fig, use_container_width=True)

                            # Display the data table for all agencies
                            st.subheader("Word Count Data by Year and Agency")

                            # Pivot the data to show years as columns and agencies as rows
                            pivot_df = time_df.pivot(index="Agency", columns="Year", values="Word Count")
                            pivot_df = pivot_df.reset_index()

                            # Format the table for display
                            st.dataframe(pivot_df, use_container_width=True)

                            # Add a download button for all selected agencies data
                            all_csv = time_df.to_csv(index=False)
                            st.download_button(
                                label="Download data as CSV",
                                data=all_csv,
                                file_name=f"wordcount_agencies_{start_year}-{end_year}.csv",
                                mime="text/csv"
                            )
                else:
                    st.info("Please select at least one agency to analyze.")
            else:
                st.warning("No agency data available. Please run the analysis in the 'Agency Analysis' tab first.")

    with tab5:
        st.header("Agency Regulation Composition by Title")

        # Check if we have the necessary data
        if 'agencies' not in st.session_state:
            with st.spinner("Fetching agency data..."):
                st.session_state.agencies = get_agencies(force_refresh=not cache_results)

        if st.session_state.agencies:
            # Extract all agency names for the dropdown
            all_agency_names = []

            def collect_agency_names(agency_list):
                for agency in agency_list:
                    all_agency_names.append(agency["name"])
                    if "children" in agency and agency["children"]:
                        collect_agency_names(agency["children"])

            collect_agency_names(st.session_state.agencies)
            all_agency_names = sorted(all_agency_names)

            # Agency selection dropdown
            selected_agency = st.selectbox(
                "Select an agency to analyze its regulatory composition:",
                options=all_agency_names
            )

            # Add note about title search scope
            st.info("""
            **Note:** This analysis searches all titles regulated by the selected agency and is not bounded by the 
            "Number of titles to process" limit in the sidebar configuration. Results will include data from all 
            applicable titles found in the eCFR API.
            """)

            if st.button("Analyze Regulatory Composition", type="primary"):
                # Create a cache key based on the parameters
                cache_key = f"agency_composition_{selected_agency.replace(' ', '_')}_{target_date_str}_{skip_problematic_titles}_{request_timeout}"

                # Check if we have cached results and caching is enabled
                if cache_results and cache_key in st.session_state:
                    st.success("Using cached results. Toggle 'Cache results' off to force recalculation.")

                    # Retrieve cached data
                    title_word_counts = st.session_state[f"{cache_key}_title_word_counts"]
                    composition_df = st.session_state[f"{cache_key}_composition_df"]
                    total_words = st.session_state[f"{cache_key}_total_words"]
                    title_fetch_errors = st.session_state.get(f"{cache_key}_title_fetch_errors", {})
                    has_data = st.session_state.get(f"{cache_key}_has_data", False)
                else:
                    # Check if titles data is available or fetch it
                    if 'titles_info' not in st.session_state:
                        with st.spinner("Fetching titles data..."):
                            st.session_state.titles_info = get_titles(force_refresh=not cache_results)

                    # Get the titles information
                    titles_info = st.session_state.titles_info

                    # Create agency-title mappings
                    agency_to_titles = create_agency_title_mapping(st.session_state.agencies)
                    titles_for_agency = agency_to_titles.get(selected_agency, set())

                    has_data = False

                    if not titles_for_agency:
                        st.warning(f"No title references found for {selected_agency}. This agency may not regulate any specific titles.")
                        composition_df = pd.DataFrame()
                        title_word_counts = {}
                        title_fetch_errors = {}
                        total_words = 0
                    else:
                        # Use current date for analysis (or the date from the sidebar)
                        target_date = target_date_str

                        # Process only the titles relevant to this agency
                        with st.spinner(f"Analyzing regulatory composition for {selected_agency}..."):
                            # Show progress
                            progress_bar = st.progress(0)
                            status_text = st.empty()

                            # Dictionary to store word counts by title
                            title_word_counts = {}
                            title_fetch_errors = {}

                            # Only process titles relevant to this agency
                            relevant_titles = [t for t in titles_info if str(t["number"]) in titles_for_agency]

                            # If no relevant titles found, try processing all titles (fallback)
                            if not relevant_titles:
                                for title_num in titles_for_agency:
                                    # Find the title info or create a placeholder
                                    title_match = next((t for t in titles_info if str(t["number"]) == str(title_num)), None)
                                    if title_match:
                                        relevant_titles.append(title_match)

                            # If we still have no titles, process all titles as a fallback
                            if not relevant_titles:
                                relevant_titles = titles_info[:10]  # Limit to first 10 titles as safety

                            for i, title_info in enumerate(relevant_titles):
                                title_number = title_info["number"]
                                title_name = title_info.get("name", "Unknown")
                                latest_date = title_info["latest_amended_on"]

                                # Update progress
                                progress = (i + 1) / len(relevant_titles)
                                progress_bar.progress(progress)
                                status_text.write(f"Processing title {i+1} of {len(relevant_titles)}: Title {title_number} - {title_name}")

                                # Skip reserved titles
                                if title_info.get("reserved", False):
                                    continue

                                # Determine date to use
                                use_date = target_date
                                if datetime.strptime(latest_date, "%Y-%m-%d") < datetime.strptime(target_date, "%Y-%m-%d"):
                                    use_date = latest_date

                                try:
                                    # Fetch and process content with cache control
                                    title_content = get_title_content(title_number, use_date, force_refresh=not cache_results)

                                    if title_content:
                                        word_count = count_words_in_xml(title_content)
                                        title_word_counts[title_number] = word_count
                                    else:
                                        title_fetch_errors[title_number] = "No content received"
                                except Exception as e:
                                    title_fetch_errors[title_number] = str(e)

                                # Add delay to avoid rate limiting
                                time.sleep(throttle_delay)

                            # Clear progress indicators
                            progress_bar.empty()
                            status_text.empty()

                            # Create DataFrame for visualization if we have data
                            composition_data = []
                            total_words = sum(title_word_counts.values()) if title_word_counts else 0

                            if title_word_counts:
                                has_data = True
                                for title_num, word_count in title_word_counts.items():
                                    # Find title name
                                    title_name = next((t["name"] for t in titles_info if t["number"] == title_num), f"Title {title_num}")

                                    # Calculate percentage
                                    percentage = (word_count / total_words) * 100 if total_words > 0 else 0

                                    composition_data.append({
                                        "Title Number": title_num,
                                        "Title": f"Title {title_num}: {title_name}",
                                        "Word Count": word_count,
                                        "Percentage": round(percentage, 2)
                                    })

                                # Create DataFrame
                                composition_df = pd.DataFrame(composition_data)
                                composition_df = composition_df.sort_values(by="Percentage", ascending=False).reset_index(drop=True)
                            else:
                                composition_df = pd.DataFrame()

                    # Cache results if enabled
                    if cache_results:
                        st.session_state[f"{cache_key}_title_word_counts"] = title_word_counts
                        st.session_state[f"{cache_key}_composition_df"] = composition_df
                        st.session_state[f"{cache_key}_total_words"] = total_words
                        st.session_state[f"{cache_key}_title_fetch_errors"] = title_fetch_errors
                        st.session_state[f"{cache_key}_has_data"] = has_data
                        # Store the cache key itself for reference
                        st.session_state[cache_key] = True

                # Display results
                if has_data and title_word_counts and not composition_df.empty:
                    st.subheader(f"Regulatory Composition for {selected_agency}")
                    st.write(f"Total Word Count: {total_words:,}")

                    # Create visualization - Pie Chart
                    st.subheader("Percentage Breakdown by Title")

                    # For better visualization, group small slices into "Other"
                    viz_df = composition_df.copy()
                    threshold = 2.0  # Percentage threshold for "Other" category

                    if len(viz_df) > 10:  # Only group if there are many titles
                        main_titles = viz_df[viz_df["Percentage"] >= threshold]
                        other_titles = viz_df[viz_df["Percentage"] < threshold]

                        if not other_titles.empty:
                            other_sum = other_titles["Word Count"].sum()
                            other_percentage = (other_sum / total_words) * 100

                            # Create a row for "Other"
                            other_row = pd.DataFrame([{
                                "Title Number": 0,
                                "Title": "Other Titles",
                                "Word Count": other_sum,
                                "Percentage": round(other_percentage, 2)
                            }])

                            viz_df = pd.concat([main_titles, other_row]).reset_index(drop=True)

                    # Create the pie chart
                    fig = px.pie(
                        viz_df, 
                        values="Percentage", 
                        names="Title",
                        title=f"Regulatory Composition for {selected_agency}",
                        hover_data=["Word Count"],
                        labels={"Percentage": "% of Total"},
                    )

                    fig.update_traces(
                        textposition='inside', 
                        textinfo='percent+label',
                        insidetextorientation='radial'
                    )

                    st.plotly_chart(fig, use_container_width=True)

                    # Create a bar chart for better comparison - WITHOUT color heat bar
                    fig2 = px.bar(
                        viz_df,
                        x="Title",
                        y="Percentage",
                        title=f"Regulatory Composition for {selected_agency} (Bar Chart)",
                        hover_data=["Word Count"],
                        color_discrete_sequence=["#1f77b4"]  # Use a single color for all bars
                    )

                    fig2.update_layout(
                        xaxis_title="Title",
                        yaxis_title="Percentage of Total (%)",
                        xaxis={'categoryorder':'total descending'}
                    )

                    # Add percentage labels on top of the bars
                    fig2.update_traces(
                        texttemplate='%{y:.1f}%', 
                        textposition='outside'
                    )

                    st.plotly_chart(fig2, use_container_width=True)

                    # Display the full data table
                    st.subheader("Complete Breakdown by Title")
                    st.dataframe(composition_df[["Title", "Word Count", "Percentage"]], use_container_width=True)

                    # Add download button for results
                    csv = composition_df.to_csv(index=False)
                    st.download_button(
                        label=f"Download composition data for {selected_agency}",
                        data=csv,
                        file_name=f"regulatory_composition_{selected_agency.replace(' ', '_')}.csv",
                        mime="text/csv"
                    )
                else:
                    error_message = "No word count data could be obtained for the titles regulated by this agency."
                    st.warning(error_message)

                    # Show more detailed error information
                    if title_fetch_errors:
                        st.error("Details on errors encountered:")

                        error_df = pd.DataFrame([
                            {"Title": f"Title {title}", "Error": error}
                            for title, error in title_fetch_errors.items()
                        ])

                        if not error_df.empty:
                            st.dataframe(error_df, use_container_width=True)

                    # Suggest solutions
                    st.info("""
                    **Possible solutions:**
                    1. Try a different agency that regulates more common titles
                    2. Check the API connection by using other tabs first
                    3. Increase the API request delay in the advanced options to avoid rate limiting
                    4. Try with a different target date
                    """)
        else:
            st.warning("No agency data available. Please run the analysis in the 'Agency Analysis' tab first.")

    with tab6:
      st.header("About This App")
      
      st.markdown("""
      ## Federal Regulations Word Count Analysis Tool
  
      This application analyzes the Electronic Code of Federal Regulations (eCFR) to calculate and visualize the word count of regulations by agency and title. It provides insights into the volume and distribution of federal regulations across the U.S. government.
      """)
      
      st.subheader("Key Features")
      
      col1, col2 = st.columns(2)
      
      with col1:
          st.markdown("#### 1. Agency Analysis")
          st.markdown("""
          - Calculates word counts for all federal agencies
          - Visualizes the top 10 agencies by word count
          - Provides downloadable CSV data
          """)
          
          st.markdown("#### 3. Agency Hierarchy Visualization")
          st.markdown("""
          - Interactive sunburst chart showing agency relationships
          - Filtering options for parent agencies and independent agencies
          - Tabular view of agency hierarchical structure
          """)
          
          st.markdown("#### 5. Regulatory Composition")
          st.markdown("""
          - Analyzes the distribution of an agency's regulations across different titles
          - Provides pie charts and bar charts showing percentage breakdowns
          - Helps identify which titles contribute most to an agency's regulatory footprint
          """)
      
      with col2:
          st.markdown("#### 2. Title Analysis")
          st.markdown("""
          - Displays word counts for each CFR title
          - Identifies the largest titles by word count
          - Offers visualization and downloadable data
          """)
          
          st.markdown("#### 4. Word Count Over Time")
          st.markdown("""
          - Tracks changes in regulatory word counts across multiple years
          - Allows selection of specific agencies for time series comparison
          - Interactive line chart with data download options
          """)
      
      st.subheader("Technical Capabilities")
      
      tech_col1, tech_col2 = st.columns(2)
      
      with tech_col1:
          st.markdown("""
          - **Caching System**: Stores results to improve performance and reduce API calls
          - **Throttling Controls**: Adjustable delay between API requests to prevent rate limiting
          """)
      
      with tech_col2:
          st.markdown("""
          - **Error Handling**: Robust handling of timeouts and problematic titles
          - **Advanced Configuration**: Customizable timeout settings and title processing options
          """)
      
      st.subheader("Understanding the CFR")
      
      st.markdown("""
      The Code of Federal Regulations (CFR) is divided into 50 titles that represent broad areas subject to federal regulation:
  
      - Titles 1-16: General Administrative Functions
      - Titles 17-27: Economic Regulation
      - Titles 28-41: Labor and National Defense
      - Titles 42-50: Public Health and Welfare
  
      Each title contains regulations from multiple agencies. When a title is regulated by multiple agencies, the word count is distributed proportionally among those agencies.
      """)
      
      st.subheader("Data Processing")
      
      st.markdown("""
      1. The app connects to the eCFR API to fetch data about agencies, titles, and regulations
      2. It creates mappings between agencies and the titles they regulate
      3. For each title, it retrieves the full XML content as of the selected date
      4. It parses the XML content using BeautifulSoup to calculate accurate word counts
      5. It allocates word counts to agencies based on the titles they regulate
      6. Results are visualized using Matplotlib and Plotly
      """)
      
      st.subheader("Usage Tips")
      
      st.markdown("""
      - Use the sidebar to configure analysis parameters
      - Increase the API request delay for more reliable results
      - Enable "Skip known large titles" option if experiencing timeouts
      - The cache feature speeds up repeated analyses with the same parameters
      """)
      
      st.subheader("Data Attribution")
      
      st.markdown("""
      All regulation data is sourced from the [eCFR API](https://www.ecfr.gov) provided by the U.S. Government Publishing Office.
      """)

if __name__ == "__main__":
    main()
