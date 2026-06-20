import Foundation
import Speech

struct AppleSTTConfig {
    var localeIdentifier = "de-DE"
    var audioPath: String?
    var timeoutSeconds: Double = 60
    var checkOnly = false
}

enum AppleSTTError: Error, CustomStringConvertible {
    case usage
    case missingAudioPath
    case recognizerUnavailable(String)
    case authorizationDenied(SFSpeechRecognizerAuthorizationStatus)
    case recognitionFailed(String)
    case timedOut

    var description: String {
        switch self {
        case .usage:
            return "Usage: apple_stt [--check] [--locale de-DE] [--timeout 60] /path/to/audio.wav"
        case .missingAudioPath:
            return "Missing audio file path."
        case .recognizerUnavailable(let locale):
            return "Speech recognizer is unavailable for locale \(locale)."
        case .authorizationDenied(let status):
            return "Speech recognition authorization failed with status \(speechAuthorizationStatusName(status))."
        case .recognitionFailed(let message):
            return "Recognition failed: \(message)"
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

func parseArgs(_ args: [String]) throws -> AppleSTTConfig {
    var config = AppleSTTConfig()
    var index = 1

    while index < args.count {
        let arg = args[index]
        if arg == "--locale" {
            index += 1
            guard index < args.count else { throw AppleSTTError.usage }
            config.localeIdentifier = args[index]
        } else if arg == "--timeout" {
            index += 1
            guard index < args.count, let timeout = Double(args[index]) else { throw AppleSTTError.usage }
            config.timeoutSeconds = timeout
        } else if arg == "--check" {
            config.checkOnly = true
        } else if arg == "--help" || arg == "-h" {
            throw AppleSTTError.usage
        } else if config.audioPath == nil {
            config.audioPath = arg
        } else {
            throw AppleSTTError.usage
        }
        index += 1
    }

    if !config.checkOnly && config.audioPath == nil {
        throw AppleSTTError.missingAudioPath
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
        throw AppleSTTError.timedOut
    }

    guard authorizationStatus == .authorized else {
        throw AppleSTTError.authorizationDenied(authorizationStatus)
    }
}

func checkAvailability(config: AppleSTTConfig) throws -> String {
    let locale = Locale(identifier: config.localeIdentifier)
    guard let recognizer = SFSpeechRecognizer(locale: locale) else {
        throw AppleSTTError.recognizerUnavailable(config.localeIdentifier)
    }

    return "recognizer=yes locale=\(recognizer.locale.identifier) available=\(recognizer.isAvailable)"
}

func transcribe(config: AppleSTTConfig) throws -> String {
    let locale = Locale(identifier: config.localeIdentifier)
    guard let recognizer = SFSpeechRecognizer(locale: locale), recognizer.isAvailable else {
        throw AppleSTTError.recognizerUnavailable(config.localeIdentifier)
    }

    guard let audioPath = config.audioPath else {
        throw AppleSTTError.missingAudioPath
    }

    let audioURL = URL(fileURLWithPath: audioPath)
    let request = SFSpeechURLRecognitionRequest(url: audioURL)
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = false
    if #available(macOS 13.0, *) {
        request.addsPunctuation = true
    }

    var completed = false
    var finalText = ""
    var finalError: Error?

    let task = recognizer.recognitionTask(with: request) { result, error in
        if let result {
            finalText = result.bestTranscription.formattedString
            if result.isFinal {
                completed = true
            }
        }

        if let error {
            finalError = error
            completed = true
        }
    }

    if !runLoopUntil(timeoutSeconds: config.timeoutSeconds, condition: { completed }) {
        task.cancel()
        throw AppleSTTError.timedOut
    }

    if let finalError {
        throw AppleSTTError.recognitionFailed(finalError.localizedDescription)
    }

    let trimmed = finalText.trimmingCharacters(in: .whitespacesAndNewlines)
    if trimmed.isEmpty {
        throw AppleSTTError.recognitionFailed("No speech was recognized.")
    }

    return trimmed
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
    try requestSpeechAuthorization(timeoutSeconds: config.timeoutSeconds)
    if config.checkOnly {
        print(try checkAvailability(config: config))
    } else {
        let transcript = try transcribe(config: config)
        print(transcript)
    }
    exit(0)
} catch let error as AppleSTTError {
    fputs("\(error.description)\n", stderr)
    exit(error.description.hasPrefix("Usage:") ? 2 : 1)
} catch {
    fputs("\(error.localizedDescription)\n", stderr)
    exit(1)
}
