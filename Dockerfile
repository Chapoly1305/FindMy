FROM python:3.12

# Install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Clone the repository
RUN git clone https://github.com/Chapoly1305/FindMy.git
WORKDIR /app/FindMy

# Create and activate virtual environment
RUN python3 -m venv venv
ENV PATH="/app/FindMy/venv/bin:$PATH"

# Install dependencies
RUN pip3 install -r requirements.txt

# Create volume for keys directory to persist data
VOLUME /app/FindMy/keys

# Expose port 8000
EXPOSE 8000

# Start the web service
CMD ["python3", "web_service.py"]