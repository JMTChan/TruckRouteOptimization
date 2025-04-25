import streamlit as st
import folium
import requests
import polyline
import pandas as pd
import numpy as np
from streamlit_folium import folium_static

# Google Maps API Key
st.set_page_config(page_title="Truck Route Optimizer (Hybrid)", layout="wide")
GOOGLE_MAPS_API_KEY = ""  # <-- Replace with your Google Maps API Key

# Warehouse coordinates
warehouse = {'name': 'Warehouse', 'lat': 6.189746, 'lng': 125.089500}
st.title("🚛 Truck Route Optimizer (Hybrid Approach)")
st.markdown("Prioritize stops with higher sales and optimize routes using real-time traffic + OR-Tools.")

# Inject CSS for responsiveness
st.markdown(
    """
    <style>
        @media (max-width: 768px) {
            .st-container {
                padding-left: 10px !important;
                padding-right: 10px !important;
            }
            .st-columns {
                flex-direction: column !important;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---- UPLOAD DATA ----
upload_option = st.radio("Upload Method", ["Excel File", "Google Sheet URL"])
if upload_option == "Excel File":
    excel_file = st.file_uploader("Upload Excel File (.xlsx)", type=["xlsx"])
    if excel_file:
        df = pd.read_excel(excel_file)
elif upload_option == "Google Sheet URL":
    sheet_url = st.text_input("Paste your Google Sheets URL")
    if sheet_url and "docs.google.com" in sheet_url:
        csv_url = sheet_url.replace("/edit#gid=", "/export?format=csv&gid=")
        try:
            df = pd.read_csv(csv_url)
        except:
            st.error("❌ Failed to fetch Google Sheet. Make sure it's public.")

if 'df' in locals():
    required_cols = {"Trade Name", "Map Coordinates", "AVERAGE PER PURCHASE"}
    if required_cols.issubset(set(df.columns)):
        try:
            df[['lat', 'lng']] = df['Map Coordinates'].str.split(",", expand=True).astype(float)
            df['sales'] = df['AVERAGE PER PURCHASE']
            # Use 'Trade Name' as the key for the location name
            st.session_state.locations = df[['Trade Name', 'lat', 'lng', 'sales']].rename(columns={'Trade Name': 'name'}).to_dict(orient="records")
            st.success("✅ Data loaded and parsed.")
            st.dataframe(df[['Trade Name', 'lat', 'lng', 'sales']])
        except Exception as e:
            st.error(f"❌ Error parsing coordinates: {e}")
    else:
        st.error(f"❌ Missing columns. Required: {', '.join(required_cols)}")

# Load the locations from session state
if "locations" not in st.session_state:
    st.session_state.locations = []

st.title("🚚 Truck Route Optimizer (Google Maps)")
st.markdown("Prioritize stops with higher sales and optimize delivery routes using Google Maps.")

# Function to get road route (polyline) with traffic data
def get_road_route(start, end):
    url = (
        f"https://maps.googleapis.com/maps/api/directions/json"
        f"?origin={start['lat']},{start['lng']}"
        f"&destination={end['lat']},{end['lng']}"
        f"&departure_time=now"
        f"&traffic_model=best_guess"
        f"&mode=DRIVING"  # Explicitly set travel mode to driving
        f"&key={GOOGLE_MAPS_API_KEY}"
    )
    try:
        res = requests.get(url)
        res.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        data = res.json()

        if data.get("status") == "OK":
            encoded = data["routes"][0]["overview_polyline"]["points"]
            traffic_duration = data["routes"][0]["legs"][0]["duration_in_traffic"]["value"]
            return polyline.decode(encoded), traffic_duration
        else:
            st.error(f"❌ Google Maps Directions API error: {data.get('status')}.  Details: {data.get('error_message', 'No error message provided')}")
            return [(start['lat'], start['lng']), (end['lat'], end['lng'])], 0  # Return a straight line as fallback
    except requests.exceptions.RequestException as e:
        st.error(f"❌ Error fetching directions: {e}")
        return [(start['lat'], start['lng']), (end['lat'], end['lng'])], 0  # Return a straight line as fallback

# Function to solve TSP using nearest neighbor
def solve_tsp_nearest_neighbor(distance_matrix):
    num_locations = len(distance_matrix)
    visited = [False] * num_locations
    order = [0]  # Start from warehouse
    visited[0] = True
    current_location = 0

    while len(order) < num_locations:
        min_distance = float('inf')
        next_location = None
        for i in range(num_locations):
            if not visited[i] and distance_matrix[current_location][i] < min_distance:
                min_distance = distance_matrix[current_location][i]
                next_location = i
        visited[next_location] = True
        order.append(next_location)
        current_location = next_location

    return order

if st.button("🚀 Optimize & Show Full Route") and st.session_state.locations:
    with st.spinner("Optimizing route using real-time data..."):
        # Prepare locations and distance matrix
        locations = st.session_state.locations
        num_locations = len(locations) + 1  # Including warehouse

        # Prepare the distance matrix
        distance_matrix = np.zeros((num_locations, num_locations))

        # Fill the distance matrix with traffic durations
        all_points = [warehouse] + locations
        st.session_state.all_points = all_points # Store for segment selection

        # Solve TSP
        route_order = solve_tsp_nearest_neighbor(distance_matrix)

        # Map the route order back to the original locations
        ordered_route = [all_points[i] for i in route_order]
        st.session_state.ordered_route = ordered_route # Store the ordered route
        st.session_state.show_map = True # Flag to show the map

if "ordered_route" in st.session_state and st.session_state.show_map:
    st.subheader("🗺 Route Viewer")
    col1, col2 = st.columns([1, 3]) # Adjust column widths as needed

    with col1:
        all_stops_names = ["Show Full Route"] + [p['name'] for p in st.session_state.ordered_route[:-1]] # Exclude the last stop for individual segments
        selected_option = st.selectbox("Select Route to Display", all_stops_names)

    with col2:
        st.markdown(
            """
            <style>
                .folium-map {
                    width: 100%;
                    height: 600px; /* Or any fixed height you prefer */
                }
            </style>
            """,
            unsafe_allow_html=True,
        )
        m_display = folium.Map(location=[warehouse['lat'], warehouse['lng']], zoom_start=12)

        # Add markers for all stops in the optimized route
        for i, point in enumerate(st.session_state.ordered_route):
            icon_color = "blue" if point['name'] != 'Warehouse' else "purple"
            icon_type = "shopping-cart" if point['name'] != 'Warehouse' else "home"
            tooltip_text = point['name']
            folium.Marker(
                location=[point["lat"], point["lng"]],
                tooltip=tooltip_text,
                icon=folium.Icon(color=icon_color, icon=icon_type, prefix="fa")
            ).add_to(m_display)

        if selected_option == "Show Full Route":
            # Display the full optimized route
            for i in range(1, len(st.session_state.ordered_route)):
                start = st.session_state.ordered_route[i - 1]
                end = st.session_state.ordered_route[i]
                coords, traffic_duration = get_road_route(start, end)

                line_color = "green" if traffic_duration < 600 else "yellow" if traffic_duration < 1800 else "red"
                if isinstance(coords, list) and all(isinstance(coord, tuple) and len(coord) == 2 for coord in coords):
                    folium.PolyLine(coords, color=line_color, weight=4, opacity=0.8).add_to(m_display)
        elif selected_option != "Show Full Route":
            # Display route segment from the selected stop to the next
            start_stop_name = selected_option
            start_index = -1
            for i, stop in enumerate(st.session_state.ordered_route):
                if stop['name'] == start_stop_name:
                    start_index = i
                    break

            if start_index != -1 and start_index < len(st.session_state.ordered_route) - 1:
                start_point = st.session_state.ordered_route[start_index]
                end_point = st.session_state.ordered_route[start_index + 1]

                coords, traffic_duration = get_road_route(start_point, end_point)

                line_color = "green" if traffic_duration < 600 else "yellow" if traffic_duration < 1800 else "red"
                if isinstance(coords, list) and all(isinstance(coord, tuple) and len(coord) == 2 for coord in coords):
                    folium.PolyLine(coords, color=line_color, weight=5, opacity=0.8).add_to(m_display)
                else:
                    st.warning(f"Could not retrieve valid polyline data for the segment: {start_point['name']} to {end_point['name']}")
            elif start_index == len(st.session_state.ordered_route) - 1:
                st.info(f"Selected stop: {selected_stop_name} is the last stop.")
            else:
                st.warning(f"Could not find stop: {start_stop_name} in the optimized route.")

        m_display.get_root().html.add_to(m_display)
        folium_static(m_display, height=600)
