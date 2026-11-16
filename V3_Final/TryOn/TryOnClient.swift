import Foundation

/// Where the try-on server is. Set at build time (see README), or at run time
/// through UserDefaults for development.
nonisolated struct TryOnConfig: Sendable {
    let serverURL: URL?
    let appKey: String

    static var current: TryOnConfig {
        let defaults = UserDefaults.standard
        let info = Bundle.main.infoDictionary ?? [:]
        let urlText = (defaults.string(forKey: "tryOnServerURL") ?? info["TryOnServerURL"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let key = (defaults.string(forKey: "tryOnAppKey") ?? info["TryOnAppKey"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let url = urlText.isEmpty ? nil : URL(string: urlText)
        return TryOnConfig(serverURL: (url?.scheme?.hasPrefix("http") == true) ? url : nil, appKey: key)
    }
}

/// Talks to the try-on server (see backend/README.md for the API).
nonisolated struct TryOnClient: Sendable {

    nonisolated struct Garment: Sendable {
        let category: String
        let png: Data
    }

    private nonisolated struct TokenResponse: Decodable { let token: String }
    private nonisolated struct HealthResponse: Decodable { let categories: [String] }
    private nonisolated struct LayerResponse: Decodable { let layer: String }
    private nonisolated struct RenderResponse: Decodable { let image: String }
    private nonisolated struct ErrorBody: Decodable { let code: String; let message: String }
    private nonisolated struct ErrorResponse: Decodable { let error: ErrorBody }

    private static let tokenKey = "tryOnDeviceToken"

    private static let session: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 200       // a generation can take a while
        configuration.timeoutIntervalForResource = 400
        configuration.waitsForConnectivity = false
        return URLSession(configuration: configuration)
    }()

    // MARK: - Calls

    /// The categories the server can try on right now.
    func supportedCategories() async throws -> [String] {
        let config = try configuration()
        let request = URLRequest(url: config.url.appendingPathComponent("healthz"))
        let data = try await send(request)
        return try decode(HealthResponse.self, from: data).categories
    }

    /// One garment on the avatar, returned as a transparent PNG in the studio frame.
    func layer(avatarPNG: Data, garmentPNG: Data, category: String, pose: BodyPose?) async throws -> Data {
        var form = MultipartForm()
        form.add(file: avatarPNG, name: "avatar", fileName: "avatar.png")
        form.add(file: garmentPNG, name: "garment", fileName: "garment.png")
        form.add(text: category, name: "category")
        form.add(text: TryOnStudio.backgroundHex, name: "background")
        if let pose = pose?.jsonString { form.add(text: pose, name: "pose") }

        let data = try await authorized(path: "v1/layers", form: form)
        guard let png = Data(base64Encoded: try decode(LayerResponse.self, from: data).layer) else {
            throw TryOnFailure(code: "bad_response", message: "The layer could not be decoded.")
        }
        return png
    }

    /// The whole outfit generated garment after garment, as one finished image.
    func render(avatarPNG: Data, garments: [Garment], pose: BodyPose?) async throws -> Data {
        var form = MultipartForm()
        form.add(file: avatarPNG, name: "avatar", fileName: "avatar.png")
        for (index, garment) in garments.enumerated() {
            form.add(file: garment.png, name: "garments", fileName: "garment\(index).png")
        }
        let names = try JSONSerialization.data(withJSONObject: garments.map(\.category))
        form.add(text: String(data: names, encoding: .utf8) ?? "[]", name: "categories")
        form.add(text: TryOnStudio.backgroundHex, name: "background")
        if let pose = pose?.jsonString { form.add(text: pose, name: "pose") }

        let data = try await authorized(path: "v1/renders", form: form)
        guard let image = Data(base64Encoded: try decode(RenderResponse.self, from: data).image) else {
            throw TryOnFailure(code: "bad_response", message: "The image could not be decoded.")
        }
        return image
    }

    // MARK: - Plumbing

    private func configuration() throws -> (url: URL, appKey: String) {
        let config = TryOnConfig.current
        guard let url = config.serverURL else { throw TryOnFailure.notConfigured }
        return (url, config.appKey)
    }

    /// Sends a form with this installation's token, registering first if needed.
    private func authorized(path: String, form: MultipartForm) async throws -> Data {
        let config = try configuration()
        for attempt in 0..<2 {
            let token = try await deviceToken(config: config)
            var request = URLRequest(url: config.url.appendingPathComponent(path))
            request.httpMethod = "POST"
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            request.setValue(form.contentType, forHTTPHeaderField: "Content-Type")
            request.httpBody = form.body
            do {
                return try await send(request)
            } catch let failure as TryOnFailure where failure.code == "unauthorized" && attempt == 0 {
                // The server's secret changed: forget the token and register again, once.
                UserDefaults.standard.removeObject(forKey: TryOnClient.tokenKey)
            }
        }
        throw TryOnFailure(code: "unauthorized", message: "The try-on service refused this app.")
    }

    private func deviceToken(config: (url: URL, appKey: String)) async throws -> String {
        if let token = UserDefaults.standard.string(forKey: TryOnClient.tokenKey), !token.isEmpty {
            return token
        }
        var request = URLRequest(url: config.url.appendingPathComponent("v1/devices"))
        request.httpMethod = "POST"
        request.setValue(config.appKey, forHTTPHeaderField: "X-App-Key")
        let data = try await send(request)
        let token = try decode(TokenResponse.self, from: data).token
        UserDefaults.standard.set(token, forKey: TryOnClient.tokenKey)
        return token
    }

    private func send(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await TryOnClient.session.data(for: request)
        } catch {
            throw TryOnFailure.offline
        }
        guard let http = response as? HTTPURLResponse else { throw TryOnFailure.offline }
        guard (200..<300).contains(http.statusCode) else {
            if let body = try? JSONDecoder().decode(ErrorResponse.self, from: data) {
                throw TryOnFailure(code: body.error.code, message: body.error.message)
            }
            throw TryOnFailure(code: http.statusCode == 401 ? "unauthorized" : "server_error",
                               message: "The try-on service answered with an error (\(http.statusCode)).")
        }
        return data
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw TryOnFailure(code: "bad_response", message: "The try-on service sent an unexpected answer.")
        }
    }
}

/// A multipart/form-data body.
nonisolated struct MultipartForm: Sendable {
    private let boundary = "outfit-" + UUID().uuidString
    private var data = Data()

    var contentType: String { "multipart/form-data; boundary=\(boundary)" }

    var body: Data {
        var body = data
        body.append(Data("--\(boundary)--\r\n".utf8))
        return body
    }

    mutating func add(text: String, name: String) {
        data.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(text)\r\n".utf8))
    }

    mutating func add(file: Data, name: String, fileName: String, mimeType: String = "image/png") {
        data.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"; filename=\"\(fileName)\"\r\nContent-Type: \(mimeType)\r\n\r\n".utf8))
        data.append(file)
        data.append(Data("\r\n".utf8))
    }
}
