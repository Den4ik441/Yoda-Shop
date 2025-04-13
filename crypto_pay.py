import requests
import json
import config
from datetime import datetime

class CryptoPay:
    
    BASE_URL = "https://pay.crypt.bot/api"
    
    def __init__(self, api_token=None):
        self.api_token = api_token or config.CRYPTO_PAY_API_TOKEN
        
    def _make_request(self, method, endpoint, params=None):
        url = f"{self.BASE_URL}/{endpoint}"
        headers = {"Crypto-Pay-API-Token": self.api_token}
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=params)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            print(f"Request URL: {url}")
            print(f"Request headers: {headers}")
            print(f"Request params: {params}")
            print(f"Response status: {response.status_code}")
            print(f"Response content: {response.text[:500]}...")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error making request to {endpoint}: {e}")
            print(f"Full error: {str(e)}")
            if hasattr(e, 'response') and e.response:
                print(f"Error response: {e.response.text}")
            return {"ok": False, "error": str(e)}
    
    def get_me(self):
        return self._make_request("GET", "getMe")

    
    def get_balance(self):
        return self._make_request("GET", "getBalance")
    
    def create_invoice(self, amount, asset=None, currency_type=None, fiat=None, 
                      accepted_assets=None, description=None, hidden_message=None, 
                      paid_btn_name=None, paid_btn_url=None, payload=None, 
                      allow_comments=None, allow_anonymous=None, expires_in=None):
        if currency_type is None:
            currency_type = "crypto"
        params = {"amount": str(float(amount))}
        if currency_type == "crypto":
            if asset is None:
                asset = "USDT"
            params["asset"] = asset
        elif currency_type == "fiat":
            if fiat is None:
                raise ValueError("Для currency_type='fiat' необходимо указать параметр fiat")
            params["fiat"] = fiat
            if accepted_assets:
                params["accepted_assets"] = accepted_assets
        if description:
            params["description"] = description
        if hidden_message:
            params["hidden_message"] = hidden_message
        if paid_btn_name and paid_btn_url:
            valid_btn_names = ["viewItem", "openChannel", "openBot", "callback"]
            if paid_btn_name not in valid_btn_names:
                print(f"Предупреждение: paid_btn_name '{paid_btn_name}' недопустим. Используется 'callback'.")
                paid_btn_name = "callback"
            params["paid_btn_name"] = paid_btn_name
            params["paid_btn_url"] = paid_btn_url
        if payload:
            params["payload"] = payload
        if allow_comments is not None:
            params["allow_comments"] = allow_comments
        if allow_anonymous is not None:
            params["allow_anonymous"] = allow_anonymous
        if expires_in:
            params["expires_in"] = expires_in
        
        print(f"Creating invoice with params: {params}")
        return self._make_request("POST", "createInvoice", params)
    
    def create_check(self, amount, asset, pin_to_user_id=None, pin_to_username=None, description=None, expires_in=None):
        params = {
            "asset": asset,
            "amount": str(float(amount))
        }
        
        if pin_to_user_id:
            params["pin_to_user_id"] = pin_to_user_id
        if pin_to_username:
            params["pin_to_username"] = pin_to_username
        if description:
            params["description"] = description
        if expires_in:
            params["expires_in"] = expires_in
        
        print(f"Creating check with params: {params}")
        result = self._make_request("POST", "createCheck", params)
        
        if not result.get("ok", False) and isinstance(result.get("error"), dict):
            error = result.get("error")
            
            if error.get("name") == "NOT_ENOUGH_COINS":
                balance_info = self.get_balance()
                available_balance = "Неизвестно"
                
                if balance_info.get("ok", False):
                    for currency in balance_info.get("result", []):
                        if currency.get("currency_code") == asset:
                            available_balance = currency.get("available", "0")
                            break
                
                error_msg = f"Недостаточно средств для создания чека. Запрошено: {amount} {asset}, доступно: {available_balance} {asset}"
                print(error_msg)
                result["error_details"] = error_msg
            
            elif error.get("name") == "AMOUNT_TOO_SMALL":
                min_amount = error.get("min_check_amount_in_usd", 0.02)
                error_msg = f"Сумма чека слишком мала. Минимальная сумма для вывода: {min_amount}$ USDT"
                print(error_msg)
                result["error_details"] = error_msg
        
        return result
    
    def delete_invoice(self, invoice_id):
        params = {"invoice_id": invoice_id}
        return self._make_request("POST", "deleteInvoice", params)
    
    def delete_check(self, check_id):
        params = {"check_id": check_id}
        return self._make_request("POST", "deleteCheck", params)
    
    def get_invoices(self, asset=None, fiat=None, invoice_ids=None, status=None, offset=None, count=None):
        params = {}
        
        if asset:
            params["asset"] = asset
        if fiat:
            params["fiat"] = fiat
        if invoice_ids:
            if isinstance(invoice_ids, list):
                params["invoice_ids"] = ",".join(str(i) for i in invoice_ids)
            else:
                params["invoice_ids"] = str(invoice_ids)
        if status:
            params["status"] = status
        if offset is not None:
            params["offset"] = offset
        if count is not None:
            params["count"] = count
        
        return self._make_request("GET", "getInvoices", params)
    
    def get_checks(self, asset=None, check_ids=None, status=None, offset=None, count=None):
        params = {}
        
        if asset:
            params["asset"] = asset
        if check_ids:
            if isinstance(check_ids, list):
                params["check_ids"] = ",".join(str(i) for i in check_ids)
            else:
                params["check_ids"] = str(check_ids)
        if status:
            params["status"] = status
        if offset is not None:
            params["offset"] = offset
        if count is not None:
            params["count"] = count
        
        return self._make_request("GET", "getChecks", params)
    
    def get_exchange_rates(self):
        return self._make_request("GET", "getExchangeRates")
    
    def get_currencies(self):
        return self._make_request("GET", "getCurrencies")
    
    def test_api_connection(self):
        try:
            response = self.get_me()
            if response.get("ok", False):
                print("✅ API подключение успешно установлено!")
                print(f"Информация об аккаунте: {response.get('result', {})}")
                return True
            else:
                print("❌ Ошибка API подключения!")
                print(f"Ответ API: {response}")
                return False
        except Exception as e:
            print(f"❌ Исключение при подключении к API: {e}")
            return False