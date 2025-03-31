import json
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from openai import RateLimitError
import time


def load_json(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        print("✅ JSON file loaded successfully!")
        return data
    except Exception as e:
        print(f"❌ Error loading JSON: {e}")
        return None


def extract_page_details(data):
    page_details = []

    def extract_from_node(node, parent=None):
        for page_name, details in node.items():
            current_page = {
                "name": page_name,
                "parent": parent,
                "elements": details.get("elements", []),
                "network_requests": details.get("network", []),
                "storage": details.get("storage", {}),
                "sub_pages": []
            }

            if "sub_pages" in details:
                current_page["sub_pages"] = extract_from_node(details["sub_pages"], page_name)

            page_details.append(current_page)
        return page_details

    return extract_from_node(data)


def generate_test_plan(page_details, openai_api_key):
    try:
        llm = ChatOpenAI(
            model_name="gpt-3.5-turbo",  # Changed to widely available model
            openai_api_key=openai_api_key,
            temperature=0.7
        )

        prompt_template = PromptTemplate(
            input_variables=["page_info"],
            template="""
            As a senior QA automation engineer, analyze the following page details and generate comprehensive test scenarios:

            Page: {page_info[name]}
            Parent Page: {page_info[parent]}

            Page Elements Found: {page_info[elements_count]}
            Network Requests: {page_info[network_count]}
            Storage Items: {page_info[storage_count]}

            Generate a detailed test plan covering:
            1. UI Functionality Tests (validate all interactive elements)
            2. API/Network Tests (verify critical API calls)
            3. Performance Tests (based on network timings)
            4. Storage Validation (localStorage, sessionStorage)
            5. Security Tests (XSS, data protection)
            6. Accessibility Tests (WCAG compliance)

            For each test category provide:
            - Test Objective
            - Preconditions
            - Detailed Test Steps
            - Expected Results
            - Severity/Priority

            Include specific element selectors and API endpoints where applicable.
            """
        )

        test_cases = []
        for page in page_details:
            try:
                # Prepare page info summary
                page_info = {
                    "name": page["name"],
                    "parent": page["parent"],
                    "elements_count": len(page["elements"]),
                    "network_count": len(page["network_requests"]),
                    "storage_count": len(page["storage"])
                }

                prompt = prompt_template.format(page_info=page_info)

                # Add rate limiting delay
                time.sleep(2)  # 2 second delay between API calls

                response = llm.invoke(prompt)
                test_cases.append(f"=== TEST PLAN FOR: {page['name']} ===")
                test_cases.append(response.content)
                test_cases.append("\n" + "=" * 50 + "\n")

            except RateLimitError:
                print(f"⚠️ Rate limit exceeded for page {page['name']}. Using detailed fallback.")
                test_cases.append(generate_fallback_test_case(page))
            except Exception as e:
                print(f"⚠️ Error generating test case for {page['name']}: {e}")
                test_cases.append(generate_fallback_test_case(page))

        return test_cases
    except Exception as e:
        print(f"❌ Error initializing OpenAI client: {e}")
        return ["Error: Could not initialize OpenAI client"]


def generate_fallback_test_case(page):
    """Generate a detailed test case without AI when API fails"""
    test_case = [
        f"=== MANUAL TEST PLAN FOR: {page['name']} ===",
        f"Parent Page: {page.get('parent', 'Root')}",
        "\nUI FUNCTIONALITY TESTS:",
        "1. Verify all buttons and interactive elements are clickable",
        "2. Validate form submissions work properly",
        "3. Check all navigation links direct to correct pages",
        f"4. Test these specific elements: {', '.join(el['selector'] for el in page.get('elements', [])[:5])}",

        "\nNETWORK TESTS:",
        "1. Verify critical API endpoints return 200 status",
        f"2. Check these endpoints: {', '.join(req['url'] for req in page.get('network_requests', [])[:3])}",
        "3. Validate response formats match expectations",

        "\nSTORAGE TESTS:",
        "1. Verify localStorage items are set/retrieved properly",
        f"2. Check these storage items: {', '.join(page.get('storage', {}).keys())}",
        "3. Validate cookie settings",

        "\nACCESSIBILITY CHECKS:",
        "1. Verify alt text for images",
        "2. Check color contrast ratios",
        "3. Validate keyboard navigation",
        "\n" + "=" * 50 + "\n"
    ]
    return "\n".join(test_case)


def save_test_plan(test_cases, output_file="generated_test_plan.txt"):
    try:
        with open(output_file, "w", encoding="utf-8") as file:
            file.write("\n\n".join(test_cases))
        print(f"✅ Comprehensive Test Plan saved to {output_file}!")
    except Exception as e:
        print(f"❌ Error saving test plan: {e}")


if __name__ == "__main__":
    json_file_path = "portal_scan_report.json"
    openai_api_key = "Add your Open API Key here"  # Replace with valid key

    data = load_json(json_file_path)

    if data:
        page_details = extract_page_details(data)
        print(f"✅ Extracted details for {len(page_details)} pages")

        test_cases = generate_test_plan(page_details, openai_api_key)
        save_test_plan(test_cases)