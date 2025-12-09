# API Reference

This document provides a detailed reference for the Spectra API.

## Base URL

All API endpoints are prefixed with `/api`. The base URL for the API is `http://localhost:5000/api`.

## Authentication

Most endpoints require authentication using a JWT token.

- **Header:** `Authorization: Bearer <token>`
- **Obtaining a Token:** Use `/api/auth/token` with username and password.

---

## Core Endpoints

### Health Check

- **GET `/health`**
  - **Description:** Check if the API server is running.
  - **Response:** `{"status": "ok"}`

### System Status

- **GET `/system/status`**
  - **Description:** detailed system health including DB, Redis, and Tool readiness.
  - **Response:**
    ```json
    {
      "status": "ready",
      "components": {
        "database": true,
        "redis": true
      },
      "initialization": {
        "tools_installed": 10,
        "tools_total": 12
      }
    }
    ```

---

## Mission Management

### Create Mission

- **POST `/missions`**
  - **Description:** Start a new security assessment mission.
  - **Body:**
    ```json
    {
      "target": "example.com",
      "directive": "Full security audit focusing on web vulnerabilities."
    }
    ```
  - **Response:** `Mission` object with `id`.

### Get Mission Status

- **GET `/missions/{mission_id}`**
  - **Description:** Retrieve current status, logs, and findings for a mission.

### Stop Mission

- **POST `/missions/{mission_id}/stop`**
  - **Description:** Gracefully stop a running mission.

---

## Tool Management

### List Tools

- **GET `/tools`**
  - **Description:** List all registered tool plugins.

### Get Tool Details

- **GET `/tools/{tool_id}`**
  - **Description:** Get configuration and status for a specific tool.

---

## Exploitation & POCs

### List Exploits

- **GET `/exploits`**
  - **Description:** List history of exploit attempts.

### Web Shell Connection

- **WebSocket `/shell/{session_id}`**
  - **Description:** Connect to an interactive reverse shell session.
  - **Protocol:** WebSocket
  - **Data:** Raw text input/output.

---

## Targets

### List Targets

- **GET `/targets`**
  - **Description:** List all scoped targets and their status.

### Add Target manually

- **POST `/targets`**
  - **Body:** `{"address": "192.168.1.1", "description": "Manual target"}`

---

## Authentication & Setup

### Setup System

- **POST `/auth/setup`**
  - **Description:** Initialize the admin account (only available if no users exist).

### Login

- **POST `/auth/token`**
  - **Content-Type:** `application/x-www-form-urlencoded`
  - **Body:** `username=...&password=...`
  - **Response:** `{"access_token": "...", "token_type": "bearer"}`
