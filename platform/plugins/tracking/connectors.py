from sdk.connector import RESTConnector, WebhookConnector, CSVConnector, EmailConnector

class ShippingLineConnector(RESTConnector):
    connector_id = "shipping_line_generic"

class AirlineAWBConnector(RESTConnector):
    connector_id = "airline_awb_generic"

class CourierTrackingConnector(RESTConnector):
    connector_id = "courier_tracking_generic"

class TrackingWebhookConnector(WebhookConnector):
    connector_id = "tracking_webhook_generic"

class TrackingCSVConnector(CSVConnector):
    connector_id = "tracking_csv_generic"

class TrackingEmailConnector(EmailConnector):
    connector_id = "tracking_email_generic"
