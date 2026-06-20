import AVFoundation
import Foundation
import Speech

struct LiveSTTConfig {
    var localeIdentifier = "de-DE"
    var timeoutSeconds: Double = 300
}

enum LiveSTTError: Error, CustomStringConvertible {
    case usage
    case authorizationDenied(SFSpeechRecognizerAuthorizationStatus)
    case recognizerUnavailable(String)
    case microphoneUnavailable
    case engineFailed(String)
    case timedOut

    var description: String {
        switch self {
        case .usage:
            return "Usage: apple_live_stt [--locale de-DE] [--timeout 300]"
        case .authorizationDenied(let status):
            return "Speech recognition authorization failed with status \(speechAuthorizationStatusName(status))."
        case .recognizerUnavailable(let locale):
            return "Speech recognizer is unavailable for locale \(locale)."
        case .microphoneUnavailable:
            return "Microphone input is unavailable."
        case .engineFailed(let message):
            return "Audio engine failed: \(message)"
        case .timedOut:
            return "Recognition timed out."
        }
    }
}

func speechAuthorizationStatusName(_ status: SFSpeechRecognizerAuthorizationStatus) -> String {
    switch status {
    case .notDetermined:
        return "notDetermined"
    case .denied:
        return "denied"
    case .restricted:
        return "restricted"
    case .authorized:
        return "authorized"
    @unknown default:
        return "unknown(\(status.rawValue))"
    }
}

func parseArgs(_ args: [String]) throws -> LiveSTTConfig {
    var config = LiveSTTConfig()
    var index = 1

    while index < args.count {
        let arg = args[index]
        if arg == "--locale" {
            index += 1
            guard index < args.count else { throw LiveSTTError.usage }
            config.localeIdentifier = args[index]
        } else if arg == "--timeout" {
            index += 1
            guard index < args.count, let timeout = Double(args[index]) else { throw LiveSTTError.usage }
            config.timeoutSeconds = timeout
        } else if arg == "--help" || arg == "-h" {
            throw LiveSTTError.usage
        } else {
            throw LiveSTTError.usage
        }
        index += 1
    }

    return config
}

func requestSpeechAuthorization(timeoutSeconds: Double) throws {
    var completed = false
    var authorizationStatus = SFSpeechRecognizerAuthorizationStatus.notDetermined

    SFSpeechRecognizer.requestAuthorization { status in
        authorizationStatus = status
        completed = true
    }

    if !runLoopUntil(timeoutSeconds: timeoutSeconds, condition: { completed }) {
        throw LiveSTTError.timedOut
    }

    guard authorizationStatus == .authorized else {
        throw LiveSTTError.authorizationDenied(authorizationStatus)
    }
}

func emit(_ type: String, _ text: String = "") {
    let payload: [String: String] = ["type": type, "text": text]
    if let data = try? JSONSerialization.data(withJSONObject: payload),
       let line = String(data: data, encoding: .utf8) {
        print(line)
        fflush(stdout)
    }
}

func emitError(_ message: String) {
    let payload: [String: String] = ["type": "error", "text": message]
    if let data = try? JSONSerialization.data(withJSONObject: payload),
       let line = String(data: data, encoding: .utf8) {
        print(line)
        fflush(stdout)
    }
}

func runLiveRecognition(config: LiveSTTConfig) throws {
    let locale = Locale(identifier: config.localeIdentifier)
    guard let recognizer = SFSpeechRecognizer(locale: locale), recognizer.isAvailable else {
        throw LiveSTTError.recognizerUnavailable(config.localeIdentifier)
    }

    let audioEngine = AVAudioEngine()
    let inputNode = audioEngine.inputNode
    let format = inputNode.outputFormat(forBus: 0)

    if format.channelCount == 0 {
        throw LiveSTTError.microphoneUnavailable
    }

    let request = SFSpeechAudioBufferRecognitionRequest()
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = true
    if #available(macOS 13.0, *) {
        request.addsPunctuation = true
    }

    var completed = false
    var lastText = ""

    let task = recognizer.recognitionTask(with: request) { result, error in
        if let result {
            let text = result.bestTranscription.formattedString
            if text != lastText {
                lastText = text
                emit(result.isFinal ? "final" : "partial", text)
            }
            if result.isFinal {
                completed = true
            }
        }

        if let error {
            emitError(error.localizedDescription)
            completed = true
        }
    }

    inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
        request.append(buffer)
    }

    audioEngine.prepare()
    do {
        try audioEngine.start()
    } catch {
        task.cancel()
        inputNode.removeTap(onBus: 0)
        throw LiveSTTError.engineFailed(error.localizedDescription)
    }

    emit("ready")

    let finished = runLoopUntil(timeoutSeconds: config.timeoutSeconds, condition: { completed })
    audioEngine.stop()
    inputNode.removeTap(onBus: 0)
    request.endAudio()
    task.cancel()

    if !finished {
        throw LiveSTTError.timedOut
    }
}

func runLoopUntil(timeoutSeconds: Double, condition: () -> Bool) -> Bool {
    let deadline = Date().addingTimeInterval(timeoutSeconds)
    while !condition() && Date() < deadline {
        RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05))
    }
    return condition()
}

do {
    let config = try parseArgs(CommandLine.arguments)
    try requestSpeechAuthorization(timeoutSeconds: min(config.timeoutSeconds, 30))
    try runLiveRecognition(config: config)
    exit(0)
} catch let error as LiveSTTError {
    emitError(error.description)
    exit(error.description.hasPrefix("Usage:") ? 2 : 1)
} catch {
    emitError(error.localizedDescription)
    exit(1)
}
