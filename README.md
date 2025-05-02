Overview
This application connects to the official eCFR API to retrieve the full text of federal regulations, count words, and provide interactive visualizations showing how regulatory burden is distributed across government agencies. It allows researchers, policymakers, and citizens to better understand the scale and growth of federal regulations over time.
Features
📊 Agency Analysis

Calculate total word counts across all federal agencies
Visualize top agencies by regulation volume
Compare senior agencies vs. all agencies (including subagencies)
Download complete data as CSV

📚 Title Analysis

Examine word counts across the 50 titles of the Code of Federal Regulations
Identify which regulatory areas have the highest word counts
View and download title-specific data

🌳 Agency Hierarchy Visualization

Interactive sunburst chart displaying the organizational structure of federal regulatory agencies
Filter views by parent agency or view independent agencies
Examine relationships between parent and child agencies

📈 Word Count Over Time

Track changes in regulatory word counts across years (2010-2025)
Select specific agencies for time-series comparison
Visualize regulatory growth patterns over multiple administrations

🔍 Regulatory Composition

Analyze how an agency's regulations are distributed across different titles
Identify which regulatory titles contribute most to an agency's footprint
View percentage breakdowns through interactive pie and bar charts

Usage

Select a date cutoff (default: current year)
Choose the number of titles to process
Configure advanced options like caching and request timing

Navigate between the tabs to access different analysis views

Analysis Workflow

Start with the Agency Analysis tab and click "Calculate Word Counts"
Once the initial analysis is complete, explore the other tabs which will use the cached data
For time series analysis, select years and agencies in the Word Count Over Time tab
To examine a specific agency's regulatory profile, use the Regulatory Composition tab

Implementation Details
Key Components

eCFR API Integration: Connects to the official Electronic Code of Federal Regulations API
Word Count Engine: Parses XML content using BeautifulSoup and counts words accurately
Agency-Title Mapping: Creates relationships between agencies and the titles they regulate
Caching System: Stores results to improve performance and reduce API load
Visualization Engine: Uses Matplotlib and Plotly for interactive data visualization

Technologies Used

Streamlit: Web application framework
Pandas: Data manipulation and analysis
BeautifulSoup: XML parsing
Matplotlib & Plotly: Data visualization
NetworkX: Graph analysis for agency hierarchy
Requests: API interaction

API Endpoints Used
This application uses the following eCFR API endpoints:

https://www.ecfr.gov/api/admin/v1/agencies.json - Retrieves agency data
https://www.ecfr.gov/api/versioner/v1/titles.json - Retrieves title metadata
https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title_number}.xml - Retrieves full XML content for a title

Advanced Usage
Performance Considerations

Caching: Enable caching to store results and avoid redundant API calls
Throttling: Adjust the API request delay to prevent rate limiting
Timeouts: Increase request timeout for large titles (7, 10, 40, 42, 45)
Title Selection: Process fewer titles for faster results during initial testing

API Limitations

The eCFR API may have rate limits or occasional downtime
Some large titles may cause timeouts due to their size
Historical data before 2010 may not be consistently available
