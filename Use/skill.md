# Agent Skills — Learned Resolution Patterns

## Domain: IT Helpdesk for Banking & Financial Services

### Printer & Hardware
- **Passbook printer jams**: Open the front cover, remove the jammed passbook, check the feed roller for debris, clean with compressed air, and re-align the paper guide.
- **Laser printer offline**: Check USB/network cable, restart the print spooler service (`net stop spooler && net start spooler`), re-add the printer if needed.
- **Canon printer paper feed issues**: Check paper tray alignment, clean pickup rollers with a lint-free cloth dampened with water.

### Password & Access
- **AD password resets**: Use Active Directory Users and Computers → right-click user → Reset Password. Ensure "User must change password at next logon" is checked.
- **Account lockouts**: Check event logs on the domain controller for Event ID 4740 to find the source of lockout.
- **MFA enrollment failures**: Verify the user's phone number in Azure AD, clear browser cache, use incognito mode.

### Network & Connectivity
- **Branch VPN down**: Check WAN link status, verify IPSec tunnel SA, restart the VPN service on the router.
- **DNS resolution failures**: Flush DNS cache (`ipconfig /flushdns`), verify DNS server settings, check if the DNS service is running.
- **Slow internet at branch**: Run speed test, check bandwidth utilization on the router, verify QoS policies.

### Software & Applications
- **MS Office activation issues**: Run `cscript ospp.vbs /act` from the Office installation directory, verify KMS server reachability.
- **Core banking software crashes**: Check application logs, verify Java version compatibility, clear application cache.

### Security & Vulnerability
- **Antivirus alert — false positive**: Verify the file hash against VirusTotal, add to exclusion list if confirmed safe, document the exception.
- **Phishing email reported**: Isolate the email, check sender domain against known threat lists, alert SOC if indicators match.

---

*This file is updated as the agent learns new resolution patterns from ticket analysis.*
