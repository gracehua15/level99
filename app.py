# app.py
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import anthropic
import json
import re

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_secret_key')  # Needed for session management

# Initialize the Anthropic client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Predefined list of competitor categories
COMPETITOR_CATEGORIES = [
    "Direct Competitors (e.g., Boda Borg, Activate)",
    "Escape Rooms (e.g., The Escape Game)",
    "Arcades (e.g., Dave & Busters, Round1)",
    "Bowling (e.g., Lucky Strike)",
    "Mini Golf (e.g., Puttshack, Swingers, Puttery)",
    "Social Golf (e.g., Top Golf, Five Iron)",
    "Social Ping Pong (e.g., Spin)",
    "Social Darts (e.g., Flight Club)",
    "Axe Throwing (e.g., Urban Axes)",
    "Go Karting (e.g., Supercharged Entertainment)",
    "Movie Theatre (e.g., AMC, Alamo Drafthouse, Regal)",
    "Immersive Gaming (e.g., Sandbox VR, Immersive Gamebox)",
    "Interactive Installations (e.g., WNDR Museum, Meowolf, Museum of Ice Cream, Illuminarium)"
]

# Base system prompt template for the Anthropic API - Initial Research
# Note the use of double curly braces for the JSON template to avoid format string confusion
SYSTEM_PROMPT_TEMPLATE = """
you are a very smart real estate analyst and you are very good at your job! i'd like your help on a task. i'm going to give you a list of entertainment categories. I'd like your help to find places that fall into each entertainment category, within a certain number of miles of a certain zip code.   

for each category, provide up to {results_per_category} examples. include their address and a brief description. make sure that you only show results that are still in business. do not hallucinate results. if i ask for 10 results, but there are only 4 locations that are still in business within the search radius, only return 4 results. 

here is the criteria you should use when pulling results. these are listed in order of priority:
1) have strong reputations, reviews, and visibility 
2) proximity to the zip code given (closer is better, assuming equally strong reputation)
3) the more tech-enabled they are, the better 

here are some other rules to follow: 
+ use google maps as your primary source, but feel free to supplement with other articles you come across 
+ ensure that there are no duplicate locations listed. if they share the same address, but a different name, remove one and replace if there is a suitable alternative
+ ensure that all locations provided are still in business. do not include locations that are permanently closed
+ never include Level99 as a location, as that is the company that is doing the research
+ if there are multiple locations of a company located within the radius, only include the one closer in proximity to the specified zip code.  

if any of the following locations exist within the specified radius, make sure you prioritize including them. But only include them if their corresponding entertainment category is provided. 
+ Dave & Busters (arcade)
+ Round1 (arcade)
+ Puttshack (mini golf)
+ Puttery (mini golf)
+ Top Golf (golf) 
+ Boda Borg (direct competitor) 
+ Activate (direct competitor) 
+ Spin (ping pong) 
+ Flight Club (darts)

Please structure your response as a JSON array of objects, with each object representing one competitor. Format it like this:

```json
[
  {{
    "name": "Competitor Name",
    "address": "Full Address",
    "distance": "X.X miles",
    "category": "Category Name",
    "description": "Brief description text",
    "notable_features": ["Feature 1", "Feature 2", "Feature 3"]
  }},
  // ... more competitors
]
```

Your response should ONLY contain the JSON data. Do not include any explanatory text.
"""

# System prompt for the pricing research
PRICING_PROMPT = """
You are a detailed market researcher specializing in entertainment venue pricing analysis. I need you to provide detailed pricing information for specific entertainment venues.

For each business, search for their pricing structure and format your findings using the exact template provided in the user message. Be as specific as possible with pricing, but if you cannot find exact numbers, provide the best available information and indicate any uncertainty.

Focus on finding:
- Current address and distance from the specified zip code
- Google review ratings and number of reviews
- How their pricing structure works (per person, per group, etc.) 
- Expected length of the experience in minutes
- Different prices for different times (weekday/weekend, morning/afternoon/evening)

Your response should ONLY contain the JSON data formatted precisely according to the template below. Do not include any explanatory text.

```json
[
  {
    "name": "Business Name",
    "address": "Full Address",
    "distance": "X.X miles",
    "description": "Description from previous research",
    "google_rating": "X.X/5",
    "review_count": "X,XXX",
    "pricing_structure": "Description of how pricing works",
    "experience_length": "XX minutes",
    "pricing": {
      "weekday_morning": "$XX",
      "weekday_afternoon": "$XX",
      "weekday_evening": "$XX",
      "weekend_morning": "$XX",
      "weekend_afternoon": "$XX",
      "weekend_evening": "$XX"
    }
  },
  // More businesses...
]
```
"""

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html', categories=COMPETITOR_CATEGORIES)

@app.route('/search', methods=['POST'])
def search():
    # Get form data
    city_state = request.form.get('city_state', '')
    zip_code = request.form.get('zip_code', '')
    search_radius = request.form.get('search_radius', '')
    results_per_category = request.form.get('results_per_category', '')
    print(f"results_per_category from form: '{results_per_category}'")
    
    
    # Validate results_per_category
    try:
        results_per_category = int(results_per_category)
        if results_per_category < 1:
            results_per_category = 1
    except (ValueError, TypeError):
        results_per_category = 5
    print(results_per_category)
    
    # Get selected categories
    selected_categories = request.form.getlist('categories')
    
    # Extract simple category names for the prompt
    simple_categories = []
    for category in selected_categories:
        # Extract just the main category name before the parenthesis
        match = re.match(r"([^(]+)", category)
        if match:
            simple_name = match.group(1).strip().lower()
            simple_categories.append(simple_name)
    
    # Get custom categories
    custom_categories = request.form.get('custom_categories', '')
    if custom_categories:
        # Split by comma and strip whitespace
        custom_list = [cat.strip().lower() for cat in custom_categories.split(',')]
        simple_categories.extend(custom_list)
    
    # Store search parameters in session
    session['search_params'] = {
        'city_state': city_state,
        'zip_code': zip_code,
        'search_radius': search_radius,
        'results_per_category': results_per_category,
        'selected_categories': simple_categories
    }
    
    # Generate dynamic system prompt with results_per_category
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(results_per_category=results_per_category)
    
    # Generate user prompt for Anthropic API
    user_prompt = f"""you are a very smart real estate analyst and you are very good at your job! i'd like your help on a task. i'm going to give you a list of entertainment categories. I'd like your help to find places that fall into each entertainment category, within {search_radius} miles of a certain zip code.   

here are the categories: 
{chr(10).join(['+ ' + category for category in simple_categories])}

here is the zip code: {zip_code}

Please provide up to {results_per_category} examples for each category. make sure that you only show results that are still in business. do not hallucinate results. if i ask for 10 results, but there are only 4 locations that are still in business within the search radius, only return 4 results. 

if any of the following locations exist within the specified radius, make sure you prioritize including them. But only include them if their corresponding entertainment category is provided. 
+ Dave & Busters (arcade)
+ Round1 (arcade)
+ Puttshack (mini golf)
+ Puttery (mini golf)
+ Top Golf (golf) 
+ Boda Borg (direct competitor) 
+ Activate (direct competitor) 
+ Spin (ping pong) 
+ Flight Club (darts)

"""
    
    try:
        # Call the Anthropic API
        message = client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=4000,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        # Extract the response
        response_text = message.content[0].text
        
        # Try to parse the JSON from the response
        try:
            # Look for JSON in the response
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            
            if json_match:
                json_data = json.loads(json_match.group(1))
            else:
                # Fallback: Try to parse the entire response as JSON
                json_data = json.loads(response_text)
                
            # Store the structured results in session
            session['research_results'] = json_data
        except json.JSONDecodeError:
            # If JSON parsing fails, store the raw text
            session['research_results'] = {'raw_text': response_text}
    
    except Exception as e:
        # Store error in session
        session['error'] = str(e)
    
    return redirect(url_for('results'))

@app.route('/results')
def results():
    # Get data from session
    search_params = session.get('search_params', {})
    research_results = session.get('research_results', {})
    error = session.get('error', None)
    
    # Clear error from session after retrieving it
    if 'error' in session:
        session.pop('error')
    
    return render_template('results.html', 
                          search_params=search_params,
                          results=research_results,
                          error=error)

@app.route('/select_competitors', methods=['POST'])
def select_competitors():
    # Get selected business IDs from form
    selected_ids = request.form.getlist('selected_businesses')
    app.logger.debug(f"Selected IDs in form: {selected_ids}")
    
    # Get research results from session
    research_results = session.get('research_results', [])
    
    # Initialize list for custom competitor data
    custom_competitors = []
    
    # Process form data for custom competitors
    form_data = dict(request.form)
    app.logger.debug(f"Form keys: {list(form_data.keys())}")
    
    # Extract custom competitor data
    for key in form_data:
        if key.startswith('custom_competitor_'):
            try:
                app.logger.debug(f"Found custom competitor: {key}, value: {form_data[key]}")
                competitor_data = json.loads(form_data[key])
                
                # Create a well-formed competitor object with required fields
                complete_competitor = {
                    "name": competitor_data.get('name', ''),
                    "address": competitor_data.get('address', ''),
                    "category": competitor_data.get('category', ''),
                    "distance": "Unknown",
                    "description": "Custom added competitor",
                    "notable_features": []
                }
                
                custom_competitors.append(complete_competitor)
                app.logger.debug(f"Processed custom competitor: {complete_competitor['name']} with address: {complete_competitor['address']}")
            except Exception as e:
                app.logger.error(f"Error parsing custom competitor: {e}")
    
    # Filter research results to only include selected standard businesses
    if isinstance(research_results, list):
        selected_businesses = []
        
        # Add standard competitors that were selected
        for i, business in enumerate(research_results):
            if str(i) in selected_ids:
                selected_businesses.append(business)
                app.logger.debug(f"Added standard competitor: {business['name']}")
        
        # Add all custom competitors
        for custom_competitor in custom_competitors:
            selected_businesses.append(custom_competitor)
            app.logger.debug(f"Added custom competitor to final list: {custom_competitor['name']} at {custom_competitor['address']}")
        
        # Store all selected businesses in session
        session['selected_businesses'] = selected_businesses
        app.logger.debug(f"Total businesses selected: {len(selected_businesses)}")
    else:
        # Handle case where research_results is not a list
        session['error'] = "Could not process selection. Please try again."
        return redirect(url_for('results'))
    
    return redirect(url_for('pricing_research'))

@app.route('/pricing_research')
def pricing_research():
    # Get selected businesses from session
    selected_businesses = session.get('selected_businesses', [])
    
    # Check if any businesses were selected
    if not selected_businesses:
        session['error'] = "No businesses were selected for pricing research."
        return redirect(url_for('results'))
    
    return render_template('pricing_form.html', businesses=selected_businesses)

@app.route('/get_pricing', methods=['POST'])
def get_pricing():
    # Get selected businesses from session
    selected_businesses = session.get('selected_businesses', [])
    zip_code = session.get('search_params', {}).get('zip_code', '')
    
    # Get selected business indices from form
    selected_indices = request.form.getlist('selected_businesses')
    app.logger.debug(f"Selected indices for pricing research: {selected_indices}")
    
    # Filter the businesses based on selection
    filtered_businesses = []
    for i, business in enumerate(selected_businesses):
        if str(i) in selected_indices:
            filtered_businesses.append(business)
            app.logger.debug(f"Including business in pricing research: {business['name']} at {business['address']}")
    
    # Generate list of business names with addresses
    business_info = []
    for business in filtered_businesses:
        name = business['name']
        address = business.get('address', 'Address unknown')
        description = business.get('description', 'No description available')
        business_info.append(f"{name} ({address}): {description}")
    
    # Create the prompt for pricing research
    user_prompt = f"""wonderful! now, for each of these businesses, can you provide me the following information:
* address
* distance from zip code {zip_code}
* description (copy what you wrote already)
* google reviews rating (out of 5 stars)
* number of google reviews
* description of how pricing works (e.g., price per person? price per group of up to 6 people?)
* expected length of experience (in minutes)
* weekday morning pricing:
* weekday afternoon pricing:
* weekday evening pricing:
* weekend morning pricing:
* weekend afternoon pricing:
* weekend evening pricing:

Here are the businesses I want to research:
{chr(10).join(['- ' + info for info in business_info])}

Please provide a comprehensive analysis with all pricing details for each business.
"""

    app.logger.debug(f"Prompt for pricing research: {user_prompt}")

    try:
        # Call the Anthropic API for pricing research
        message = client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=4000,
            system=PRICING_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        # Extract the response
        response_text = message.content[0].text
        app.logger.debug(f"Received response with length: {len(response_text)}")
        
        # Try to parse the JSON from the response
        try:
            # Look for JSON in the response
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            
            if json_match:
                json_data = json.loads(json_match.group(1))
            else:
                # Fallback: Try to parse the entire response as JSON
                json_data = json.loads(response_text)
                
            # Store the pricing results in session
            session['pricing_results'] = json_data
            app.logger.debug(f"Successfully parsed pricing results for {len(json_data)} businesses")
        except json.JSONDecodeError as e:
            # If JSON parsing fails, store the raw text
            app.logger.error(f"JSON parse error: {e}")
            session['pricing_results'] = {'raw_text': response_text}
    
    except Exception as e:
        # Store error in session
        app.logger.error(f"API error: {e}")
        session['error'] = str(e)
    
    return redirect(url_for('pricing_results'))

@app.route('/pricing_results')
def pricing_results():
    # Get data from session
    search_params = session.get('search_params', {})
    pricing_results = session.get('pricing_results', {})
    error = session.get('error', None)
    
    # Clear error from session after retrieving it
    if 'error' in session:
        session.pop('error')
    
    return render_template('pricing_results.html', 
                          search_params=search_params,
                          results=pricing_results,
                          error=error)

if __name__ == '__main__':
    app.run(debug=True)
