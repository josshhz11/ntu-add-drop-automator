# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install necessary system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    unzip \
    gnupg \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    ca-certificates \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# 1. Download and install Google Chrome version 131.0.6778.264 manually
RUN wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && dpkg -i /tmp/google-chrome.deb || apt-get -fy install \
    && rm /tmp/google-chrome.deb

# 2. Ensure Chrome binary is correctly linked
RUN ln -s /usr/bin/google-chrome-stable /usr/bin/google-chrome

# 3. Remove any existing ChromeDriver to avoid conflicts
RUN rm -f /usr/local/bin/chromedriver

# 4. Install ChromeDriver matching Google Chrome version 131.0.6778.264
RUN wget -q https://storage.googleapis.com/chrome-for-testing-public/131.0.6778.264/linux64/chromedriver-linux64.zip -O /tmp/chromedriver.zip \
    && unzip /tmp/chromedriver.zip -d /tmp/ \
    && mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver \
    && chmod +x /usr/local/bin/chromedriver \
    && rm -rf /tmp/chromedriver-linux64 /tmp/chromedriver.zip

# 5. Verify Chrome and ChromeDriver versions
RUN /usr/bin/google-chrome --version
RUN chromedriver --version

# 6. Set display (optional for headless operations)
ENV DISPLAY=:99

# 7. Copy requirements.txt and install Python dependencies
COPY requirements.txt /app/
WORKDIR /app
RUN pip install --no-cache-dir -r requirements.txt

# 8. Copy your application code into the container
COPY . /app

# 9. Expose port 5000 for Flask (mapped to port 80 on host)
EXPOSE 5000

# 10. Command to start the Flask app using Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]