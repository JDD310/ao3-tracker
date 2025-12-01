# Security Policy

## Supported Versions

Only the latest version of this project is supported with security updates. Previous versions are not guaranteed to be free of known vulnerabilities.

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please **do not** open a public issue. Instead, please report it privately by:

1. **Email**: Send details to the project maintainer (my contact information available in the repository)
2. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

I will acknowledge receipt of your report within 48 hours and provide an update on the status of the vulnerability within 7 days.

## Security Considerations

### Credential Storage

**Current Implementation:**
- **AO3 Passwords**: **NOT stored in database**. Passwords must be provided at runtime when login is required. Passwords are encrypted in memory while in use and immediately cleared after authentication. This is the most secure approach.
- **AO3 Username**: Stored in SQLite database (`download_settings` table) in plaintext (username is not considered sensitive)
- **IMAP Credentials**: Stored in environment variables (`AO3TRACKER_EMAIL`, `AO3TRACKER_IMAP_PASSWORD`) - **Recommended approach**
- **Pinboard API Tokens**: Stored in SQLite database in plaintext

**Password Encryption:**
- Passwords are encrypted using the `cryptography` library (Fernet symmetric encryption) when temporarily stored in job parameters
- Encryption key is derived from the `AO3TRACKER_ENCRYPTION_KEY` environment variable (if set) or a default key (development only)
- **For Production**: Always set `AO3TRACKER_ENCRYPTION_KEY` with a secure encryption key
- Passwords are decrypted only when needed for authentication and immediately cleared from memory

**Security Recommendations:**
- **Password Handling**: AO3 passwords are never persisted - they must be provided at runtime
- **Encryption Key**: Set `AO3TRACKER_ENCRYPTION_KEY` environment variable in production with a secure key
- **Environment Variables**: Use environment variables for all sensitive credentials when possible
- **Database Access**: Restrict access to the SQLite database file (`ao3_tracker.db`)
- **Never commit credentials**: All credential files are in `.gitignore` - do not commit them to version control

### Database Security

- **SQLite Database**: The application uses SQLite, which stores data in a local file (`ao3_tracker.db`)
- **File Permissions**: Ensure the database file has appropriate permissions to prevent unauthorized access
- **Backup Security**: If backing up the database, ensure backups are encrypted and stored securely
- **SQL Injection**: The application uses parameterized queries to prevent SQL injection attacks

### Network Security

- **HTTPS**: When deploying, always use HTTPS for the web interface
- **IMAP**: Uses SSL/TLS connections (`imaplib.IMAP4_SSL`)
- **Rate Limiting**: The application respects AO3's rate limits through ao3downloader, but consider implementing additional rate limiting for API endpoints in production

### Input Validation

- **URL Validation**: AO3 URLs are validated and normalized before processing
- **File Path Validation**: File paths are validated to prevent directory traversal attacks
- **API Input**: API endpoints use Pydantic models for input validation

### Data Privacy

- **Email Content**: The application processes email content from your IMAP email account
- **Local Storage**: All data is stored locally in the SQLite database
- **No External Transmission**: The application does not transmit your data to external services (except when downloading from AO3 or accessing your email)
- **Logs**: Download logs may contain sensitive information - ensure log files are stored securely

### Dependencies

- **Dependency Updates**: Regularly update dependencies to receive security patches
- **Vulnerability Scanning**: Consider using tools like `pip-audit` or `safety` to check for known vulnerabilities
- **ao3downloader**: This project integrates with ao3downloader (GPL-3.0). Ensure you're using the latest version

### Authentication & Authorization

- **No Built-in Auth**: The current implementation does not include user authentication for the web interface
- **Local Access Only**: By default, the application should be run on localhost or behind a firewall
- **Production Deployment**: If deploying publicly, implement:
  - User authentication
  - HTTPS/TLS
  - Rate limiting
  - Access controls
  - Session management

### File System Security

- **Download Directory**: Downloaded files are stored in a configurable directory - ensure appropriate permissions
- **Path Traversal**: The application validates file paths, but be cautious with user-provided paths
- **File Permissions**: Ensure downloaded files have appropriate permissions

### Known Security Limitations

1. **No Web Authentication**: The web interface does not have built-in authentication
2. **Local Database**: SQLite is suitable for single-user scenarios but may need additional security for multi-user deployments
3. **Password Memory**: While passwords are cleared from memory after use, Python strings are immutable, so complete memory clearing is best-effort (passwords will be garbage collected when functions return)
4. **Default Encryption Key**: If `AO3TRACKER_ENCRYPTION_KEY` is not set, a default key is used (not secure for production)
5. **Pinboard Tokens**: Pinboard API tokens are stored in plaintext in the database (consider encrypting if needed)

### Best Practices for Users

1. **Run Locally**: Run the application on localhost or a trusted network
2. **Set Encryption Key**: In production, always set `AO3TRACKER_ENCRYPTION_KEY` environment variable with a secure key
3. **Use Environment Variables**: Prefer environment variables for sensitive credentials (IMAP passwords)
4. **Password Handling**: Never store AO3 passwords - always provide them at runtime when needed
5. **Restrict File Permissions**: Use appropriate file permissions for database, credentials, and downloaded files
6. **Regular Updates**: Keep dependencies and the application updated
7. **Backup Security**: Encrypt backups of the database file
8. **Monitor Logs**: Regularly review logs for suspicious activity
9. **HTTPS in Production**: Always use HTTPS when exposing the web interface
10. **Firewall**: Use a firewall to restrict access to the application

### Security Checklist for Deployment

- [ ] Use HTTPS/TLS for web interface
- [ ] Implement user authentication if exposing publicly
- [ ] Set `AO3TRACKER_ENCRYPTION_KEY` environment variable with a secure encryption key
- [ ] Set appropriate file permissions on database files
- [ ] Use environment variables for sensitive configuration (IMAP credentials)
- [ ] Implement rate limiting on API endpoints
- [ ] Regularly update dependencies
- [ ] Review and restrict file system access
- [ ] Set up monitoring and logging
- [ ] Configure firewall rules appropriately
- [ ] Review and test backup/restore procedures
- [ ] Verify that AO3 passwords are not stored in the database

### Reporting Security Issues

When reporting security vulnerabilities, please include:

- **Type of vulnerability** (e.g., authentication bypass, SQL injection, XSS)
- **Affected component** (e.g., API endpoint, database, file handling)
- **Steps to reproduce**
- **Potential impact** (e.g., data exposure, unauthorized access)
- **Suggested fix** (optional but appreciated)

We take security seriously and will work to address reported vulnerabilities promptly.

## Security Updates

Security updates will be released as patches to the latest version. Critical security vulnerabilities will be addressed as quickly as possible, typically within 7 days of confirmation.

## License and Security

This project integrates with ao3downloader, which is licensed under GPL-3.0. When distributing this software, you must comply with GPL-3.0 requirements, including making source code available. This ensures security vulnerabilities can be identified and fixed by the community.

## Contact

For security-related questions or to report vulnerabilities, please contact the project maintainer through the repository's contact methods.

