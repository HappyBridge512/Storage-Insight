use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Serialize)]
pub struct BackendRequest<'a> {
    pub id: &'a str,
    pub method: &'a str,
    pub payload: Value,
}

#[derive(Debug, Deserialize)]
pub struct BackendResponse {
    pub id: Option<String>,
    pub ok: Option<bool>,
    pub result: Option<Value>,
    pub error: Option<BackendError>,
    pub event: Option<String>,
    pub payload: Option<Value>,
}

#[derive(Debug, Deserialize)]
pub struct BackendError {
    pub code: String,
    pub message: String,
}
