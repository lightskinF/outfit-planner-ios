import UIKit
import Vision
import CoreGraphics

/// Turns a cut-out photo of a person into the studio avatar.
///
/// The person is scaled and centred in the studio frame, placed on the flat
/// backdrop, and the body pose is read from the result. Everything happens on
/// the phone.
nonisolated enum AvatarBuilder {

    nonisolated struct Output {
        let cutout: UIImage     // person on transparent background, studio frame
        let base: UIImage       // the same on the flat backdrop: what the Studio shows
        let pose: BodyPose?
    }

    /// - Parameter requirePose: when true, a photo without a full, upright body is refused.
    static func build(from cutout: UIImage, requirePose: Bool) throws -> Output {
        guard let source = uprightImage(cutout), let bounds = opaqueBounds(of: source) else {
            throw AvatarProblem.noPerson
        }
        let imageSize = CGSize(width: source.width, height: source.height)
        let person = CGRect(x: bounds.minX * imageSize.width, y: bounds.minY * imageSize.height,
                            width: bounds.width * imageSize.width, height: bounds.height * imageSize.height)
        guard person.height >= 480, person.width >= 80 else { throw AvatarProblem.tooSmall }

        let canvas = TryOnStudio.canvasSize
        let scale = min(0.90 * canvas.height / person.height, 0.92 * canvas.width / person.width)
        let drawn = CGRect(x: (canvas.width - person.width * scale) / 2 - person.minX * scale,
                           y: 0.05 * canvas.height - person.minY * scale,
                           width: imageSize.width * scale, height: imageSize.height * scale)
        let upright = UIImage(cgImage: source, scale: 1, orientation: .up)

        let transparent = renderer(opaque: false).image { _ in
            upright.draw(in: drawn)
        }
        let background = TryOnStudio.backgroundRGB
        let base = renderer(opaque: true).image { context in
            UIColor(red: background.red, green: background.green, blue: background.blue, alpha: 1).setFill()
            context.fill(CGRect(origin: .zero, size: canvas))
            transparent.draw(in: CGRect(origin: .zero, size: canvas))
        }

        var pose: BodyPose?
        do {
            pose = try detectPose(in: base)
        } catch {
            if requirePose { throw error }
        }
        return Output(cutout: transparent, base: base, pose: pose)
    }

    /// The pixels of `image` the way it is displayed (camera photos are often stored rotated).
    private static func uprightImage(_ image: UIImage) -> CGImage? {
        if image.imageOrientation == .up { return image.cgImage }
        let format = UIGraphicsImageRendererFormat()
        format.scale = image.scale
        format.opaque = false
        format.preferredRange = .standard
        return UIGraphicsImageRenderer(size: image.size, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: image.size))
        }.cgImage
    }

    private static func renderer(opaque: Bool) -> UIGraphicsImageRenderer {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = opaque
        format.preferredRange = .standard      // plain sRGB, the same numbers the server sees
        return UIGraphicsImageRenderer(size: TryOnStudio.canvasSize, format: format)
    }

    /// The box around everything that is not transparent, in fractions of the image (origin top-left).
    static func opaqueBounds(of image: CGImage) -> CGRect? {
        let width = 256
        let height = max(1, Int((Double(image.height) / Double(max(image.width, 1)) * Double(width)).rounded()))
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        let drawnOK: Bool = pixels.withUnsafeMutableBytes { buffer in
            guard let context = CGContext(data: buffer.baseAddress, width: width, height: height,
                                          bitsPerComponent: 8, bytesPerRow: width * 4,
                                          space: CGColorSpaceCreateDeviceRGB(),
                                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        guard drawnOK else { return nil }

        var minX = width, minY = height, maxX = -1, maxY = -1
        for row in 0..<height {
            for column in 0..<width where pixels[(row * width + column) * 4 + 3] > 40 {
                if column < minX { minX = column }
                if column > maxX { maxX = column }
                if row < minY { minY = row }
                if row > maxY { maxY = row }
            }
        }
        guard maxX >= minX, maxY >= minY else { return nil }
        // The memory of a bitmap context starts with the top row of the image.
        return CGRect(x: CGFloat(minX) / CGFloat(width), y: CGFloat(minY) / CGFloat(height),
                      width: CGFloat(maxX - minX + 1) / CGFloat(width),
                      height: CGFloat(maxY - minY + 1) / CGFloat(height))
    }

    static func detectPose(in image: UIImage) throws -> BodyPose {
        guard let cgImage = image.cgImage else { throw AvatarProblem.noPerson }
        let request = VNDetectHumanBodyPoseRequest()
        let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
        try handler.perform([request])
        guard let body = request.results?.first else { throw AvatarProblem.noPerson }
        let points = try body.recognizedPoints(.all)

        let names: [(String, VNHumanBodyPoseObservation.JointName)] = [
            ("nose", .nose),
            ("left_shoulder", .leftShoulder), ("right_shoulder", .rightShoulder),
            ("left_elbow", .leftElbow), ("right_elbow", .rightElbow),
            ("left_wrist", .leftWrist), ("right_wrist", .rightWrist),
            ("left_hip", .leftHip), ("right_hip", .rightHip),
            ("left_knee", .leftKnee), ("right_knee", .rightKnee),
            ("left_ankle", .leftAnkle), ("right_ankle", .rightAnkle),
        ]
        var joints: [String: [Double]] = [:]
        for (name, joint) in names {
            guard let point = points[joint], point.confidence >= 0.2 else { continue }
            let x = min(max(Double(point.location.x), 0), 1)
            let y = min(max(1 - Double(point.location.y), 0), 1)    // Vision counts y from the bottom
            joints[name] = [(x * 10000).rounded() / 10000, (y * 10000).rounded() / 10000]
        }
        let pose = BodyPose(joints: joints)
        guard pose.isComplete else { throw AvatarProblem.bodyNotVisible }
        guard pose.isUpright else { throw AvatarProblem.notUpright }
        return pose
    }
}
