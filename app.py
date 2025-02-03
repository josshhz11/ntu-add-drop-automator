import redis
import json
from flask import Flask, request, jsonify, render_template, redirect, session, url_for, send_from_directory
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException, SessionNotCreatedException
from threading import Event
import threading
import time
import logging
import os

app = Flask(__name__)

# Load environment variables directly from Render
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "fallback_key_for_dev")
print(f"Loaded Secret Key: {app.secret_key}")

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Set to DEBUG for more detailed logs
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()  # Outputs logs to the console, which Docker captures
    ]
)

# Example logger usage
logger = logging.getLogger(__name__)

# Connect to Redis (Read from Environment Variables)
redis_client = redis.StrictRedis(
    host=os.environ.get("REDIS_HOST", "red-cug9uopopnds7398r2kg"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    password=os.environ.get("REDIS_PASSWORD", None),
    decode_responses=True
)


@app.route('/test-redis')
def test_redis():
    try:
        redis_client.set("test_key", "Hello, Redis!")
        value = redis_client.get("test_key")
        return f"Redis is working! Retrieved value: {value}"
    except Exception as e:
        return f"Redis connection error: {str(e)}"

# Utility function to set and get status data from Redis
def set_status_data(swap_id, data):
    redis_client.set(swap_id, json.dumps(data))

def get_status_data(swap_id):
    data = redis_client.get(swap_id)
    return json.loads(data) if data else {"status": "idle", "details": []}

@app.route('/thumbnail')
def serve_thumbnail():
    # Serve the image from the "static" directory
    return send_from_directory('static', 'thumbnail.jpg')

def validate_login():
    """
    Validates if the user is logged in by checking session data.
    Returns True if logged in, False otherwise.
    """
    if 'username' in session and 'password' in session:
        return True
    return False

CHROME_BINARY_PATH = "/usr/bin/google-chrome"
CHROMEDRIVER_PATH = "/usr/local/bin/chromedriver"

def create_driver():
    """
    Create and return a new Selenium WebDriver instance.
    """
    options = Options()
    options.binary_location = CHROME_BINARY_PATH
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')  # Avoid shared memory crashes
    options.add_argument('--window-size=1920x1080')  # Optional, for better rendering

    service = Service(CHROMEDRIVER_PATH)
    return webdriver.Chrome(service=service, options=options)

def login_to_portal(driver, username, password, swap_id):
    """
    Log in to the NTU portal.
    """
    url = 'https://wish.wis.ntu.edu.sg/pls/webexe/ldap_login.login?w_url=https://wish.wis.ntu.edu.sg/pls/webexe/aus_stars_planner.main'
    driver.get(url)

    username_field = driver.find_element(By.ID, "UID")
    username_field.send_keys(username)
    ok_button = driver.find_element(By.XPATH, "//input[@value='OK']")
    ok_button.click()

    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "PW")))

    password_field = driver.find_element(By.ID, "PW")
    password_field.send_keys(password)
    ok_button = driver.find_element(By.XPATH, "//input[@value='OK']")
    ok_button.click()

    # Check if login is successful or redirected to a different page
    try:
        # Wait for the URL to either be the expected URL or the alternate URL
        WebDriverWait(driver, 10).until(
        lambda d: d.current_url in [
            "https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_PLANNER.planner",
            "https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_PLANNER.time_table"
        ]
    )
        
        # Check if redirected to the time_table URL
        if driver.current_url == "https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_PLANNER.time_table":
            # Check for the "Plan/ Registration" button
            try:
                plan_button = driver.find_element(By.XPATH, "//input[@value='Plan/ Registration']")
                plan_button.click()
                logger.info("Clicked the 'Plan/ Registration' button to proceed to the planner.")
            except Exception as e:
                error_message = "Unable to find or click the 'Plan/ Registration' button."
                update_overall_status(swap_id, status="Error", message=error_message)
                logger.error(f"{error_message} {e}")
                return False
          
        # Proceed to wait for the table if on the planner page
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//table[@bordercolor='#E0E0E0']"))
        )
    # If login fails, print exception
    except Exception:
        # If login fails, update status and exit
        error_message = "Incorrect username/password. Please try again."
        update_overall_status(swap_id, status="Error", message=error_message)
        logger.error(error_message)
        return False

@app.route('/')
def index():
    # Open Graph metadata
    og_data = {
        "title": "NTU Add Drop Automator",
        "description": "Helping NTU students automate add drop swapping.",
        "image": "https://ntu-add-drop-automator.site/thumbnail.jpg",
        "url": "https://ntu-add-drop-automator.site/"
    }
    # Check for logout or timeout messages
    message = session.pop('logout_message', None)
    return render_template('index.html', message=message, og_data=og_data)

@app.route('/input-index', methods=['POST'])
def input_index():
    try:
        session['username'] = request.form['username']
        session['password'] = request.form['password']
        num_modules = int(request.form['numModules'])
        if num_modules <= 0:
                raise ValueError("Invalid number of modules")
        
        return render_template('input_index.html', num_modules=num_modules)
    except Exception as e:
        logger.error(f"Error in input_index: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/swap-status', methods=['GET'])
def render_swap_status():
    # Validate login
    if not validate_login():
        return render_template('error.html', message="You are not logged in. Please log in to continue.")

    # Retrieve swap data
    swap_id = session.get("swap_id")
    if not swap_id:
        return jsonify({"status": "idle", "details": [], "message": None})
    
    status_data = get_status_data(swap_id)
    
    # Return status data as JSON for dynamic updates
    return jsonify(status_data)

@app.route('/swap-index', methods=['POST'])
def swap_index():
    # Check if user is logged in
    if 'username' not in session or 'password' not in session:
        return redirect(url_for('index'))
    
    try:
        # Get form data
        number_of_modules = request.form.get('number_of_modules')
        if not number_of_modules:
            app.logger.error("number_of_modules not found in form data")
            raise ValueError("Number of modules not provided")
            
        number_of_modules = int(number_of_modules)
        if number_of_modules <= 0:
            raise ValueError("Invalid number of modules")
        
        swap_items = []  # List to store (old_index, new_indexes, swapped)
        for i in range(number_of_modules):
            old_index = request.form.get(f'old_index_{i}')
            new_indexes_raw = request.form.get(f'new_index_{i}')
            if not old_index or not new_indexes_raw:
                raise ValueError(f"Missing index data for module {i+1}")
            
            # Parse new indexes into a list
            new_indexes = [index.strip() for index in new_indexes_raw.split(",") if index.strip()]
            if not new_indexes:
                raise ValueError(f"Invalid new index data for module {i+1}")
            
            swap_items.append({
                "old_index": old_index,
                "new_indexes": new_indexes,
                "swapped": False
            })
        
        # Generate a unique ID for this swap session
        swap_id = f"{session['username']}_{int(time.time())}"
        session["swap_id"] = swap_id

         # Initialize Redis with status data
        status_data = {
            "status": "Processing",
            "details": [{"old_index": item["old_index"], 
                         "new_indexes": ", ".join(item["new_indexes"]), 
                         "swapped": False,
                         "message": "Pending..."} for item in swap_items],
            "message": None
        }
        set_status_data(swap_id, status_data)
        
        username = session['username']
        password = session['password']
        
        thread = threading.Thread(target=perform_swaps, args=(username, password, swap_items, swap_id), daemon=True)
        thread.start()

        # Render the status page initially
        return render_template('swap_status.html',
                               status=status_data["status"],
                               details=status_data["details"],
                               message=status_data["message"])
    except Exception as e:
        app.logger.error(f"Error in swap_index: {str(e)}")
        return jsonify({"error": str(e)}), 500

def perform_swaps(username, password, swap_items, swap_id):
    driver = None

    try:
        # Browser setup
        driver = create_driver()
        login_to_portal(driver, username, password, swap_id)

        start_time = time.time()
        while True:
            for idx, item in enumerate(swap_items):
                if not item["swapped"]:
                    failed_indexes = []
                    for new_index in item["new_indexes"]:
                        try:
                            success, message = attempt_swap(
                                old_index=item["old_index"],
                                new_index=new_index,
                                idx=idx,
                                driver=driver,
                                swap_id=swap_id
                            )
                            if success:
                                item["swapped"] = True
                                update_status(
                                    swap_id,
                                    idx,
                                    message=f"Successfully swapped index {item['old_index']} to {item['new_index']}.",
                                    success=True
                                )
                                break
                            else:
                                failed_indexes.append(new_index)
                        except WebDriverException as e:
                            logger.error(f"WebDriver error: {e}")
                            driver.quit()
                            driver.create_driver() # Restart the browser
                            login_to_portal(driver, username, password)
                            failed_indexes.append(new_index)
                        except Exception as e:
                            error_message = f"Error during swap attempt: {e}"
                            update_status(swap_id, idx, message=error_message)
                            logger.error(error_message)
                            failed_indexes.append(new_index)
                    if not item["swapped"] and failed_indexes:
                        update_status(
                            swap_id,
                            idx,
                            message=f"Index {', '.join(failed_indexes)} have no vacancies."
                        )
            # Check if all items are swapped
            all_swapped = all(item["swapped"] for item in swap_items)
            if all_swapped:
                update_overall_status(swap_id, status="Completed", message=f"All modules have been successfully swapped.")
                break

            if time.time() - start_time >= 2 * 3600:
                update_overall_status(swap_id, status="Timed Out", message="Time limit reached before completing the swap.")
                logger.error("Time limit reached before completing the swap.")
                break

            time.sleep(5 * 60)
    except Exception as e:
        update_overall_status(swap_id, status="Error", message=f"An error occurred: {str(e)}")
        logger.error(f"An error occurred: {str(e)}")
    finally:
        if driver:
            driver.quit()

def attempt_swap(old_index, new_index, idx, driver, swap_id):
    """
    Returns True if swap was successful, False otherwise.
    """    
    try:
        update_status(swap_id, idx, f"Attempting to swap {old_index} -> {new_index}")
        # 1) Wait for the table element to appear on the main page
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//table[@bordercolor='#E0E0E0']"))
        )

        # 2) Locate the radio button for old_index by its value attribute and click it.
        try:
            # Wait for the radio button to be present
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, f"//input[@type='radio' and @value='{old_index}']"))
            )
            
            # Locate and click the radio button
            radio_button = driver.find_element(By.XPATH, f"//input[@type='radio' and @value='{old_index}']")
            radio_button.click()

        except TimeoutException:
            # If the radio button is not found within the timeout period
            error_message = f"Old index  {old_index} not found. Swap cannot proceed."
            update_status(swap_id, idx, error_message)
            update_overall_status(swap_id, status="Error", message=error_message)
            logger.error(error_message)
            return False, error_message  # Return a value indicating failure

        except Exception as e:
            # Handle any unexpected errors
            error_message = f"Unexpected error locating radio button for index {old_index}: {str(e)}"
            update_status(swap_id, idx, error_message)
            logger.error(error_message)
            return False, error_message  # Return a value indicating failure

        # 3) Select the "Change Index" option from the dropdown
        dropdown = Select(driver.find_element(By.NAME, "opt"))
        dropdown.select_by_value("C")

        # 4) Click the 'Go' button
        header = driver.find_element(By.CLASS_NAME, "site-header__body")
        driver.execute_script("arguments[0].style.visibility = 'hidden';", header)  # Hide the header
        go_button = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Go']")
        go_button.click()

        """
        Swap index page after choosing the mod and index you want to swap
        """

        # 5) Check for an alert, if portal is closed
        try:
            WebDriverWait(driver, 5).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            alert_text = alert.text
            print(f"Alert detected: {alert_text}")
            alert.accept()  # Close the alert
            update_overall_status(swap_id, status="Error", message="Portal is closed now. Please try again from 10:30am - 10:00pm.")
            logger.error("Portal is closed now. Please try again from 10:30am - 10:00pm.")
            return False
        except TimeoutException:
            # If no alert, proceed to the swap index page
            print("No alert detected, proceeding to the swap index page.")

        # 6) Wait for the swap index page
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "AUS_STARS_MENU"))
        )

        # 7) Check if the new index exists and has vacancies
        try:
            # Locate the dropdown for selecting the new index
            dropdown_element = driver.find_element(By.NAME, "new_index_nmbr")
            
            # Locate the option for the new index
            options = dropdown_element.find_elements(By.XPATH, f".//option[@value='{new_index}']")
            
            if not options:
                # If the desired new index is not in the dropdown, handle the error
                error_message = f"New Index {new_index} was not found in the dropdown options. Swap cannot proceed."
                update_status(swap_id, idx, error_message)
                logger.error(error_message)
                
                # Click the 'Back To Timetable' button
                back_button = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Back to Timetable']")
                back_button.click()
                
                return False, error_message  # Return a value indicating failure

            # Parse the vacancies from the option text (e.g., "01172 / 9 / 1")
            option_text = options[0].text
            try:
                vacancies = int(option_text.split(" / ")[1])  # Parse out the middle number (vacancies)
                print(f"The number of vacancies for index {new_index} is {vacancies}.")
            except (IndexError, ValueError) as e:
                error_message = f"Failed to parse vacancies for index {new_index}: {str(e)}"
                update_status(swap_id, idx, error_message)
                logger.error(error_message)

                # Click the 'Back To Timetable' button
                back_button = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Back to Timetable']")
                back_button.click()

                return False, error_message

            # Select the new index in the dropdown
            select_dropdown = Select(dropdown_element)
            select_dropdown.select_by_value(new_index)

            if vacancies <= 0:
                # If there are no vacancies, handle it gracefully
                error_message = f"Index {new_index} has no vacancies. Swap cannot proceed."
                update_status(swap_id, idx, error_message)
                logger.error(error_message)

                # Click the 'Back To Timetable' button
                back_button = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Back to Timetable']")
                back_button.click()

                return False, error_message

        except Exception as e:
            # Catch any unexpected errors
            error_message = f"Unexpected error while checking new index {new_index}: {str(e)}"
            update_overall_status(swap_id, status="Error", message=error_message)
            logger.error(error_message)

            # Click the 'Back To Timetable' button
            back_button = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Back to Timetable']")
            back_button.click()
            
            return False, error_message

        # 8) Click 'OK'
        ok_button2 = driver.find_element(By.XPATH, "//input[@type='submit' and @value='OK']")
        ok_button2.click()
        
        # Catch Module Clash error with other existing modules
        try:
            WebDriverWait(driver, 5).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            alert_text = alert.text
            print(f"Alert detected: {alert_text}")
            alert.accept()  # Close the alert
            update_overall_status(swap_id, status="Error", message=alert_text)
            logger.error(alert_text)

            # Click the 'Back To Timetable' button
            back_button = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Back to Timetable']")
            back_button.click()
            
            return False, alert_text
        except TimeoutException:
            # If no alert, proceed to the swap index page
            print("No slot clash alert detected, proceeding to confirm swap index.")

        """
        Confirm Swap Index page after choosing the mod and index you want to swap
        """

        # 9) Wait for the confirm swap index page
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[@id='top']/div/section[2]/div/div/form[1]"))
        )

        # 10) Click the 'Confirm to Change Index Number' button 
        confirm_change_button = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Confirm to Change Index Number']")
        confirm_change_button.click()

        # 11) Wait for the official changed index alert to pop up and click OK
        WebDriverWait(driver, 10).until(
            EC.alert_is_present()
        )

        alert = driver.switch_to.alert
        print(f"Alert text: {alert.text}")
        alert.accept()      # Accept (click OK) on the alert

        return True, "" # Successful swap, no error message
    
    except SessionNotCreatedException as e:
        logger.error("Session expired. Re-logging in...")
        driver.quit()
        driver = create_driver()
        login_to_portal(driver, session['username'], session['password'], swap_id)
        return False, "Session expired and was refreshed. Retry swap."

    except Exception as e:
        current_url = driver.current_url
        page_title = driver.title
        error_message = (
            f"Error during swap attempt for {old_index} -> {new_index}: {e}. "
            f"Current URL: {current_url}, Page Title: {page_title}"
        )
        update_status(swap_id, idx, error_message)
        logger.error(error_message)
        return False, error_message

def update_status(swap_id, idx, message, success=False):
    """
    Updates the status of a specific module swap in Redis.

    Args:
        swap_id (str): Unique swap session ID.
        idx (int): Index of the module in the details list.
        message (str): Message to update in the status.
        success (bool): Whether the swap was successful.
    """
    status_data = get_status_data(swap_id)
    if idx < len(status_data["details"]):
        status_data["details"][idx]["message"] = message
        if success:
            status_data["details"][idx]["swapped"] = True
        set_status_data(swap_id, status_data)

def update_overall_status(swap_id, status, message):
    """
    Updates the overall status and message of the swap operation in Redis.

    Args:
        swap_id (str): Unique swap session ID.
        status (str): The overall status to set (e.g., "Error", "Completed").
        message (str): The overall message to set.
    """
    status_data = get_status_data(swap_id)  # Fetch current status_data
    status_data["status"] = status  # Update overall status
    status_data["message"] = message  # Update overall message
    set_status_data(swap_id, status_data)  # Save changes back to Redis

@app.route('/stop-swap', methods=['POST'])
def stop_swap():
    """
    Stops the ongoing swap operation and logs the user out.

    Returns:
        JSON response indicating the swap operation has been stopped.
    """
    swap_id = session.get("swap_id")
    if swap_id:
        # Update status_data in Redis
        status_data = get_status_data(swap_id)
        status_data["status"] = "Stopped"
        status_data["message"] = "The swap operation has been stopped by the user."
        set_status_data(swap_id, status_data)
        # Clear status data from Redis
        redis_client.delete(swap_id)  # Remove status data associated with the swap_id

    # Clear user session data
    session.clear() # Clear all session data
    session['logout_message'] = "You have stopped the swap and logged out."

    return jsonify({"message": "Swap operation stopped. Logging out."})

@app.route('/log-out', methods=['POST'])
def log_out():
    """
    Clears the user session and logs the user out,
    also cleans up Redis status data.
    """
    swap_id = session.get("swap_id")
    if swap_id:
        # Clear status data from Redis
        redis_client.delete(swap_id)  # Remove status data associated with the swap_id

    session.clear()  # Clear all session data
    session['logout_message'] = "Successfully logged out."
    return jsonify({"message": "You have been logged out successfully."})


if __name__ == '__main__':
    app.config['DEBUG'] = True
    app.run(host='0.0.0.0', port=5000)