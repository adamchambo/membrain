import Foundation
import MembrainSDK

func object(_ data: Data) throws -> NSDictionary {
    try JSONSerialization.jsonObject(with: data) as! NSDictionary
}
func expect(_ actual: NSDictionary, _ expected: NSDictionary) {
    precondition(actual == expected)
}
let encoder = JSONEncoder()
let decoder = JSONDecoder()
for json in [#"{"detail":"Invalid profile"}"#, #"{"detail":[{"loc":["body",0],"msg":"Invalid","type":"value_error"}]}"#] {
    let raw = Data(json.utf8)
    let model = try decoder.decode(ValidationErrorResponse.self, from: raw)
    try expect(object(encoder.encode(model)), object(raw))
}
try expect(object(encoder.encode(ResourcePatch())), [:])
try expect(object(encoder.encode(ResourcePatch(title: .encodeNull))), ["title": NSNull()])
try expect(object(encoder.encode(ResourcePatch(title: .encodeValue("Updated")))), ["title": "Updated"])
let _ = CapturesAPI()
print("Swift SDK: client construction, omitted/null PATCH fields, validation unions passed.")
