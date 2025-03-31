import json
import openai
import anthropic
import google.generativeai as genai
import time
import re
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from collections import defaultdict

# ========================
# CONFIGURATION
# ========================
AI_PROVIDER_ORDER = ["openai", "anthropic", "gemini"]  # Fallback sequence
API_KEYS = {
    "openai": "Add OpenAI Keys here",
    "anthropic": "Add Anthropic Keys here",
}
GEMINI_JSON_PATH = "C:/Automation/PortalScanner/ai-automation-455120-74adc93ac768.json"
MAX_RETRIES = 2
DELAY_BETWEEN_CALLS = 10


# ========================
# HELPER FUNCTIONS
# ========================
def load_json(file_path):
    """Load JSON data with enhanced error handling"""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
            print(f"✅ Successfully loaded {file_path}")
            return data
    except Exception as e:
        print(f"❌ Error loading {file_path}: {str(e)}")
        return None


def configure_gemini():
    """Loads Google Gemini key from JSON and configures API"""
    try:
        with open(GEMINI_JSON_PATH, "r", encoding="utf-8") as f:
            credentials = json.load(f)
        genai.configure(api_key=credentials["client_email"])
        print("✅ Gemini API configured successfully.")
    except Exception as e:
        print(f"❌ Failed to configure Gemini: {e}")


def extract_ui_elements(elements_data):
    """Enhanced element extraction with better HTML parsing"""
    if not elements_data:
        return []

    # Handle raw HTML string
    if isinstance(elements_data, str):
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(elements_data, 'html.parser')
            elements = []

            # Extract buttons
            for btn in soup.find_all(['button', 'input', '*']):
                if btn.get('type') == 'submit' or 'btn' in btn.get('class', []):
                    elements.append({
                        'type': 'button',
                        'name': btn.get('id') or btn.get('name') or btn.text[:20],
                        'locator': f"id:{btn.get('id')}" if btn.get('id') else f"text:{btn.text[:20]}"
                    })

            # Extract inputs
            for inp in soup.find_all('input'):
                elements.append({
                    'type': 'input',
                    'name': inp.get('id') or inp.get('name') or f"input-{len(elements)}",
                    'locator': f"name:{inp.get('name')}" if inp.get('name') else f"id:{inp.get('id')}"
                })

            return elements
        except ImportError:
            print("⚠️ BeautifulSoup not available for HTML parsing")
            return []

    # Handle already parsed elements
    return elements_data if isinstance(elements_data, list) else []


def extract_network_requests(network_data):
    """More flexible network request extraction"""
    if not network_data:
        return []

    requests = []

    # Handle multiple possible formats
    if isinstance(network_data, dict):
        # Try common HAR format keys
        entries = network_data.get('entries', network_data.get('logs', []))
        for entry in entries:
            if isinstance(entry, dict):
                url = entry.get('url') or entry.get('request', {}).get('url', '')
                if url:
                    requests.append({
                        'url': url,
                        'method': entry.get('method') or 'GET',
                        'status': entry.get('status') or 0,
                        'type': 'api' if 'api' in url.lower() else 'resource'
                    })

    # Handle simple list format
    elif isinstance(network_data, list):
        for req in network_data:
            if isinstance(req, dict):
                url = req.get('url', '')
                if url:
                    requests.append({
                        'url': url,
                        'method': req.get('method', 'GET'),
                        'status': req.get('status', 0),
                        'type': 'api' if 'api' in url.lower() else 'resource'
                    })

    return requests


def extract_local_storage(storage_data):
    """Extract key local storage information"""
    if not storage_data:
        return []

    items = []

    if isinstance(storage_data, dict):
        for key, value in storage_data.items():
            if key.lower().endswith('token') or key == 'user' or key == 'email':
                continue  # Skip sensitive data

            display_value = str(value)
            if len(display_value) > 50:
                display_value = display_value[:50] + '...'

            items.append({
                'key': key,
                'value': display_value,
                'type': 'storage'
            })

    elif isinstance(storage_data, list):
        for item in storage_data[:20]:  # Limit to 20 items
            if isinstance(item, dict):
                key = item.get('key', '')
                value = str(item.get('value', ''))
                if len(value) > 50:
                    value = value[:50] + '...'

                items.append({
                    'key': key,
                    'value': value,
                    'type': 'storage'
                })

    return items


def debug_data_structure():
    """Temporary function to inspect data format"""
    scan_data = load_json("portal_scan_report.json")
    if not scan_data:
        return

    print("\n=== DATA STRUCTURE DEBUG ===")
    for page, data in scan_data.items():
        print(f"\nPage: {page}")
        print("Keys:", data.keys())

        # Show sample UI elements structure
        ui_data = data.get('InspectElementHTML', data.get('elements', None))
        print("\nUI Elements Type:", type(ui_data))
        if isinstance(ui_data, str):
            print("HTML Sample:", ui_data[:100] + ("..." if len(ui_data) > 100 else ""))
        elif isinstance(ui_data, (list, dict)):
            print("Sample Elements:", str(ui_data)[:200] + ("..." if len(str(ui_data)) > 200 else ""))

        # Show sample network structure
        net_data = data.get('NetworkRequests', data.get('network_requests', None))
        print("\nNetwork Data Type:", type(net_data))
        if net_data:
            print("Sample Network Data:", str(net_data)[:200] + ("..." if len(str(net_data)) > 200 else ""))


# ========================
# AI GENERATION FUNCTIONS
# ========================
@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=DELAY_BETWEEN_CALLS, max=60),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError))
)
def generate_with_openai(page, details, scenario):
    """Generate using OpenAI API"""
    try:
        client = openai.OpenAI(api_key=API_KEYS["openai"])
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{
                "role": "user",
                "content": f"""Generate detailed Robot Framework test cases covering:
                - Page: {page}
                - Scenario: {scenario[:1000]}
                - Elements: {details.get('elements', [])[:5]}
                - APIs: {details.get('network_requests', [])[:3]}
                Include critical path, edge cases, and proper assertions."""
            }],
            temperature=0.7,
            max_tokens=2000
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"⚠️ OpenAI failed: {e}")
        raise


@retry(stop=stop_after_attempt(MAX_RETRIES))
def generate_with_anthropic(page, details, scenario):
    """Generate using Anthropic Claude"""
    try:
        client = anthropic.Client(API_KEYS["anthropic"])
        response = client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": f"""Create comprehensive Robot Framework tests for:
                Page: {page}
                Test Scenario: {scenario}
                Available Elements: {details.get('elements', [])[:10]}
                API Endpoints: {details.get('network_requests', [])[:5]}"""
            }]
        )
        return response.content[0].text
    except Exception as e:
        print(f"⚠️ Anthropic failed: {e}")
        raise


@retry(stop=stop_after_attempt(MAX_RETRIES))
def generate_with_gemini(page, details, scenario):
    """Generate using Google Gemini"""
    try:
        configure_gemini()
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(
            f"Generate Robot Framework tests for {page} with:\n"
            f"Scenario: {scenario}\n"
            f"Elements: {details.get('elements', [])[:5]}\n"
            "Include data-driven test cases"
        )
        return response.text
    except Exception as e:
        print(f"⚠️ Gemini failed: {e}")
        raise


# ========================
# FALLBACK PROCESS
# ========================
def generate_test_case(page, details, scenario):
    """Try all AI providers before falling back to local"""
    for provider in AI_PROVIDER_ORDER:
        try:
            print(f"🔄 Trying {provider} for {page}...")
            time.sleep(DELAY_BETWEEN_CALLS)

            if provider == "openai":
                return generate_with_openai(page, details, scenario)
            elif provider == "anthropic":
                return generate_with_anthropic(page, details, scenario)
            elif provider == "gemini":
                return generate_with_gemini(page, details, scenario)

        except Exception as e:
            print(f"⚠️ {provider} failed: {e}")
            continue

    print("🔴 All AI providers failed - using enhanced local generation")
    return generate_local_test_case(page, details, scenario)


def generate_local_test_case(page, details, scenario):
    """Generate structured analysis report in human-readable format"""
    try:
        # Load data directly from files with verification
        scan_data = load_json("portal_scan_report.json")
        test_plan = load_json("generated_test_plan.json")

        if scan_data is None or test_plan is None:
            print("❌ Failed to load required JSON data")
            return "=== SCAN DATA ANALYSIS ===\nError: Failed to load test data\n"

        page_scan_data = scan_data.get(page, {})

        # Start building the report
        report = f"=== SCAN DATA ANALYSIS ===\n"
        report += f"Page: {page}\n"
        report += f"URL: {page_scan_data.get('URL', 'Not available')}\n\n"

        # UI Elements Section
        ui_elements = extract_ui_elements(page_scan_data.get('InspectElementHTML',
                                                             page_scan_data.get('elements', [])))

        if ui_elements:
            report += "--- UI ELEMENTS CATEGORIZED ---\n\n"

            # Categorize elements by type
            element_categories = defaultdict(list)
            for element in ui_elements:
                if not isinstance(element, dict):
                    continue

                elem_type = element.get('type', '').lower()
                if 'button' in elem_type:
                    element_categories['button'].append(element)
                elif 'link' in elem_type or 'a href' in str(element):
                    element_categories['link'].append(element)
                elif 'input' in elem_type or 'text' in elem_type:
                    element_categories['input'].append(element)
                elif 'select' in elem_type or 'dropdown' in elem_type:
                    element_categories['dropdown'].append(element)
                elif 'checkbox' in elem_type or 'radio' in elem_type:
                    element_categories['checkbox'].append(element)
                else:
                    element_categories['other'].append(element)

            # Add each category to report
            for category, elements in element_categories.items():
                if elements:
                    report += f"{category.upper()}S ({len(elements)}):\n"
                    for elem in elements[:10]:  # Show first 10 of each type
                        name = elem.get('name', elem.get('id', elem.get('class', 'unnamed')))
                        locator = elem.get('id') or elem.get('xpath') or elem.get('selector', '')
                        report += f"- {name}"
                        if locator:
                            report += f" (Locator: {locator[:50]})"
                        report += "\n"
                    if len(elements) > 10:
                        report += f"... plus {len(elements) - 10} more\n"
                    report += "\n"
        else:
            report += "No UI elements captured\n\n"

        # Network Requests Section
        network_requests = extract_network_requests(
            page_scan_data.get('NetworkRequests',
                               page_scan_data.get('network_requests', [])))

        if network_requests:
            report += "--- NETWORK REQUESTS ---\n\n"

            # Categorize requests
            api_calls = [r for r in network_requests if '/api/' in r.get('url', '').lower()]
            static_resources = [r for r in network_requests if r not in api_calls]

            report += f"API CALLS ({len(api_calls)}):\n"
            for req in api_calls[:10]:  # Show first 10 API calls
                method = req.get('method', 'GET')
                url = req.get('url', '')
                status = req.get('status', '')
                report += f"- {method} {url.split('?')[0][:80]}"
                if status:
                    report += f" ({status})"
                report += "\n"
            if len(api_calls) > 10:
                report += f"... plus {len(api_calls) - 10} more\n"

            report += f"\nSTATIC RESOURCES ({len(static_resources)}):\n"
            for req in static_resources[:5]:  # Show first 5 static resources
                url = req.get('url', '')
                if url:
                    report += f"- {url.split('/')[-1][:50]}\n"
            if len(static_resources) > 5:
                report += f"... plus {len(static_resources) - 5} more\n"
        else:
            report += "No network requests captured\n\n"

        # Local Storage Section
        local_storage = extract_local_storage(
            page_scan_data.get('LocalStorage',
                               page_scan_data.get('local_storage', [])))

        if local_storage:
            report += "--- LOCAL STORAGE ---\n\n"

            # Filter and organize storage items
            user_data = []
            app_data = []
            sensitive_keys = ['token', 'auth', 'secret', 'password']

            for item in local_storage:
                if not isinstance(item, dict):
                    continue

                key = str(item.get('key', '')).lower()
                value = str(item.get('value', ''))

                # Skip sensitive data
                if any(s in key for s in sensitive_keys):
                    continue

                if key.startswith(('user', 'account', 'profile')):
                    user_data.append(item)
                else:
                    app_data.append(item)

            report += "USER SESSION DATA:\n"
            for item in user_data[:10]:  # Show first 10 user data items
                report += f"- {item.get('key', '')}: {item.get('value', '')[:100]}\n"
            if len(user_data) > 10:
                report += f"... plus {len(user_data) - 10} more\n"

            report += "\nAPPLICATION PREFERENCES:\n"
            for item in app_data[:10]:  # Show first 10 app preference items
                report += f"- {item.get('key', '')}: {item.get('value', '')[:100]}\n"
            if len(app_data) > 10:
                report += f"... plus {len(app_data) - 10} more\n"

            report += "\nFILTERED ITEMS (sensitive data omitted)\n"
        else:
            report += "No local storage data captured\n"

        return report

    except Exception as e:
        print(f"❌ Error generating report for {page}: {e}")
        return f"=== SCAN DATA ANALYSIS ===\nError generating report for {page}: {str(e)}\n"


# ========================
# MAIN EXECUTION
# ========================
def generate_all_test_cases():
    """Main execution with comprehensive error handling"""
    try:
        print("🚀 Starting test case generation process")

        # First run debug to check data structure
        debug_data_structure()

        # Load data with verification
        scan_data = load_json("portal_scan_report.json")
        test_plan = load_json("generated_test_plan.json")

        if not scan_data or not test_plan:
            print("❌ Critical error: Failed to load required JSON files")
            return

        print(f"📁 Found {len(scan_data)} pages in scan data")
        print(f"📄 Found {len(test_plan)} pages in test plan")

        test_cases = []
        for page, details in scan_data.items():
            print(f"\n📋 Processing page: {page}")
            scenario = test_plan.get(page, {}).get('description', f"Comprehensive test for {page}")
            test_case = generate_test_case(page, details, scenario)

            if test_case and test_case.strip():
                test_cases.append(test_case)
                print(f"✅ Generated output for {page}")
            else:
                print(f"⚠️ Empty output generated for {page}")

        if test_cases:
            with open("generated_test_cases.robot", "w", encoding="utf-8") as f:
                f.write("\n".join(test_cases))
            print(f"\n🎉 Successfully generated {len(test_cases)} outputs in generated_test_cases.robot")
            print("🔍 Please check the output file for the complete analysis")
        else:
            print("\n⚠️ No outputs were generated - check input files and logs")

    except Exception as e:
        print(f"\n❌ Fatal error in main execution: {e}")


if __name__ == "__main__":
    generate_all_test_cases()