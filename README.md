# Samsung Find Integration for Home Assistant

This integration adds support for devices from Samsung SmartThings Find. While primarily designed for Samsung SmartTags, it also works with other devices such as phones, tablets, watches, and earbuds.

The integration creates three entities for each device:
* `device_tracker`: Shows the location of the tag/device
* `sensor`: Represents the battery level of the tag/device (not supported for earbuds)
* `button`: Allows you to ring the tag/device

**Note:** This integration does **not** allow you to perform actions based on button presses on the SmartTag.

[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

## ⚠️ Important Warning/Disclaimer ⚠️

This Home Assistant integration uses an **OAuth client ID that belongs to a third party** (Samsung Find Application), not the author of this repository.

Using this client ID:

- Is **not officially supported** by the service provider.  
- May **stop working at any time** if the client ID is revoked.  
- Could potentially **violate the service’s Terms of Service (ToS)**.  
- Use this integration only for **personal or testing purposes**.  

**This integration is not officially supported by Samsung, and using it could result in your account being locked out!** 

Please be aware that I am developing this integration to the best of my knowledge and ability, but I cannot provide any guarantees. Therefore, use this integration **at your own risk**!

- **API Limitations**: This integration was created by reverse engineering the Samsung Find API
- **OAuth Flow**: It uses a reverse-engineered OAuth2 login process, which may stop working at any time if Samsung changes their systems
- **Feature Constraints**: The integration can only support features available on the [Samsung Find website](https://samsungfind.samsung.com/). For instance, stopping a SmartTag from ringing is not possible due to API limitations (while other devices do support this; not yet implemented)

## Notes on Authentication

The integration uses OAuth tokens for authentication with Samsung's services. Under normal circumstances, these OAuth tokens should not expire if everything is working correctly. The tokens are automatically refreshed every hour to maintain the connection and ensure uninterrupted service.

However, as mentioned in the warning above, this integration uses a foreign client ID from Samsung's Find Application. While the automatic token refresh mechanism works reliably under normal conditions, there is always a possibility that Samsung could revoke your tokens or change this client ID, which would cause the integration to stop working entirely.

## Notes on Device Connection
The ability to make a SmartTag ring depends on having a phone or tablet nearby that can forward your request via Bluetooth. If your phone is not near your tag, you won't be able to make it ring. However, the location should still update if any Galaxy device is nearby.

If ringing your tag doesn't work, first try making it ring from the [Samsung Find website](https://samsungfind.samsung.com/). If it doesn't work from there, it won't work from Home Assistant either! Note that making it ring with the SmartThings mobile app is not the same as using the website. Just because it works in the app doesn't mean it works on the web. Always use the web version for testing.


## Installation Instructions

### Using HACS

1. Add this repository as a custom repository in HACS. Either by manually adding `https://github.com/tomskra/ha-samsung-find` with category `integration` or simply click the following button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tomskra&repository=ha-samsung-find&category=integration)

2. Search for "Samsung Find" in HACS and install the integration
3. Restart Home Assistant
4. Proceed to [Setup instructions](#setup-instructions)

### Manual install

1. Download the `custom_components/samsung_find` directory to your Home Assistant configuration directory
2. Restart Home Assistant
3. Proceed to [Setup instructions](#setup-instructions)

## Setup Instructions

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=samsung_find)

1. Go to the Integrations page
2. Search for "Samsung Find"
3. An authentication URL will be displayed in the form. Click the link (or copy it into your browser). This URL contains an encrypted payload required for Samsung's Android SDK login method.
4. Log into your Samsung account as usual. After successful login you'll be redirected to a URL starting with `ms-app://...` – your browser will likely show an error because this scheme isn't handled. That's expected.
5. Copy the FULL redirect URL (everything beginning with `ms-app://` including all query parameters).
6. Paste this redirect URL into the Home Assistant form field and submit. The integration will decrypt the response locally, obtain the necessary user and API tokens, and finish setup.
7. Wait a few seconds for the integration to load your devices.

## Support
It’s been a fun challenge, but also a lot of hard work. If this integration has made your smart home a little more useful or convenient, and you’d like to show some support, a coffee is always appreciated. It helps keep the project going and makes the time spent on updates and improvements even more rewarding. ☕

[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

---

## Debugging

To enable debugging, you need to set the log level in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.samsung_find: debug
```

## Credits

Some logic used here is based on the [SmartThings Home Assistant integration](https://github.com/Vedeneb/HA-SmartThings-Find).
Special thanks also to the work documented in the [uTag Wiki](https://github.com/KieronQuinn/uTag), which provided valuable insights into the encrypted Android SDK authentication flow.  


## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contributions

Contributions are welcome! Feel free to open issues or submit pull requests to help improve this integration.

## Support

For support, please create an issue on the GitHub repository.

## Known issues

- Integration logo is missing (pending completion of the home-assistant/brands PR).
- Devices currently lack individual logos.

## Roadmap

- No current roadmap

## Disclaimer

This is a third-party integration and is not affiliated with or endorsed by Samsung or SmartThings.


[buymecoffee]: https://www.buymeacoffee.com/tomskra
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a-coffee-blue.svg?style=for-the-badge&logo=buymeacoffee&logoColor=ccc