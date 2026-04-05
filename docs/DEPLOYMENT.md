# Deployment Guide

This guide provides instructions for deploying the application to the production environment.

## Prerequisites
- Ensure that you have the latest version of the code.
- Docker should be installed on the production server.
- Access rights to the cloud service provider (if applicable).

## Steps to Deploy

1. **Clone the repository (if not already cloned)**:
   ```bash
   git clone https://github.com/younlec/oyelakin.git
   cd oyelakin
   ```

2. **Build the Docker image**:
   ```bash
   docker build -t oyelakin:latest .
   ```

3. **Run the Docker container**:
   ```bash
   docker run -d -p 80:80 oyelakin:latest
   ```

4. **Configure Environment Variables**: 
   Make sure to set the necessary environment variables for the application to run properly.

5. **Verify Deployment**: 
   Access the application via the browser at `http://your_production_domain` and ensure everything is working as expected.

## Rollback Instructions
If you encounter any issues, revert to the previous version of the application:
```bash
docker stop <container_id>
docker rm <container_id>
docker run -d -p 80:80 oyelakin:previous_version
```

## Additional Notes
- Keep your images updated to the latest version to avoid vulnerabilities.
- For large deployments, consider using orchestration tools like Kubernetes.
